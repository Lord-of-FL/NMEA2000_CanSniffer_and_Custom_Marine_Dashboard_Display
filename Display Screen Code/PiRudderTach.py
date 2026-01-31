#!/usr/bin/env python3
import os
import time
import subprocess
import pygame
import serial
import math
import RPi.GPIO as GPIO

time.sleep(5)
os.environ["DISPLAY"] = ":0"

BUTTON_PIN = 18
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

pygame.init()
info = pygame.display.Info()
print("Detected screen resolution:", info.current_w, "x", info.current_h)

SCREEN_WIDTH = info.current_w
SCREEN_HEIGHT = info.current_h
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.FULLSCREEN)
pygame.display.set_caption("Gauge Display")
clock = pygame.time.Clock()

GAUGE_TOP_CENTER = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 4 - 15)
GAUGE_BOTTOM_CENTER = (SCREEN_WIDTH // 2, SCREEN_HEIGHT * 3 // 4 + 15)
smaller_dim = min(SCREEN_WIDTH, SCREEN_HEIGHT)
GAUGE_RADIUS = int(smaller_dim * 0.3)

BACKGROUND_COLOR = (81, 194, 210)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
GRAY = (255, 255, 255)
WHITE = (255, 255, 255)

# ================= SERIAL CONFIG =================
SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUD = 57600

# If we don't receive a GOOD frame for this long, we consider data "stale" and go to no-data UI.
DATA_STALE_SECONDS = 1.0

# If serial isn't present, retry opening periodically.
SERIAL_RETRY_SECONDS = 2.0

ser = None
last_serial_try_time = 0.0
last_good_frame_time = 0.0

heading_font = pygame.font.SysFont("Arial", int(smaller_dim * 0.07))

rudder_angle = 180                 # centered
engine_rpm = 3000                  # centered
smoothed_engine_rpm = 3000         # centered
smoothed_rudder_angle = 180        # centered
shift_indicator = None
fuel_consumption = None

def map_value(value, in_min, in_max, out_min, out_max):
    return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

def try_open_serial():
    """Try to open the serial port. Safe if Arduino is off/unplugged."""
    global ser, last_serial_try_time
    now = time.monotonic()
    if ser is not None:
        return
    if now - last_serial_try_time < SERIAL_RETRY_SECONDS:
        return

    last_serial_try_time = now
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0.05)
        # Non-blocking-ish read:
        ser.reset_input_buffer()
        print(f"Serial opened: {SERIAL_PORT} @ {SERIAL_BAUD}")
    except Exception as e:
        ser = None
        # Keep it quiet-ish; uncomment if you want logs:
        # print(f"Serial open failed: {e}")

def close_serial():
    global ser
    try:
        if ser is not None:
            ser.close()
    except Exception:
        pass
    ser = None

def set_no_data_state():
    """UI defaults when no fresh serial data is available."""
    global rudder_angle, engine_rpm, smoothed_engine_rpm, smoothed_rudder_angle
    global shift_indicator, fuel_consumption

    # Center both needles as requested
    smoothed_rudder_angle = 180
    smoothed_engine_rpm = 3000

    rudder_angle = smoothed_rudder_angle
    engine_rpm = smoothed_engine_rpm

    # Show "-" in boxes
    shift_indicator = None
    fuel_consumption = None

def process_serial_data():
    global rudder_angle, engine_rpm, smoothed_engine_rpm, smoothed_rudder_angle
    global shift_indicator, fuel_consumption, last_good_frame_time, ser

    if ser is None:
        return

    try:
        # Read a line if available (timeout is short).
        raw = ser.readline()
        if not raw:
            return

        data = raw.decode("utf-8", errors="ignore").strip()
        if not data:
            return

        values = data.split(",")
        if len(values) < 4:
            return

        pot_value = int(values[0])
        pot_value2 = int(values[1])
        shift_indicator = int(values[2])
        fuel_consumption = float(values[3])

        new_rudder_angle = map_value(pot_value, 0, 4095, 240, 120)   # your existing mapping
        new_engine_rpm = map_value(pot_value2, 0, 4095, 0, 6000)

        alpha = 0.3
        if smoothed_engine_rpm == 0:
            smoothed_engine_rpm = new_engine_rpm
        else:
            smoothed_engine_rpm = alpha * new_engine_rpm + (1 - alpha) * smoothed_engine_rpm

        if smoothed_rudder_angle == 0:
            smoothed_rudder_angle = new_rudder_angle
        else:
            smoothed_rudder_angle = alpha * new_rudder_angle + (1 - alpha) * smoothed_rudder_angle

        rudder_angle = smoothed_rudder_angle
        engine_rpm = smoothed_engine_rpm

        # Mark fresh data time ONLY after a full valid parse
        last_good_frame_time = time.monotonic()

    except Exception as e:
        # If Arduino power drops mid-read, pyserial can throw. Drop serial and keep UI alive.
        print("Serial error:", e)
        close_serial()

def draw_water_waves(surface, t):
    num_waves = 22
    amplitude = 10
    period = 300
    speed = 0.0002
    for i in range(num_waves):
        base_y = 100 + i * 40
        phase = t * speed * (i + 1)
        points = []
        for x in range(0, SCREEN_WIDTH, 4):
            y = base_y + amplitude * math.sin(2 * math.pi * x / period + phase)
            points.append((x, y))
        pygame.draw.lines(surface, WHITE, False, points, 2)

def draw_dotted_arc(surface, center, radius, start_deg, end_deg, step_deg, dot_radius, color):
    for deg in range(start_deg, end_deg + 1, step_deg):
        theta = math.radians(deg)
        x = center[0] + math.cos(theta) * radius
        y = center[1] + math.sin(theta) * radius
        pygame.draw.circle(surface, color, (int(x), int(y)), dot_radius)

def draw_boat_shape(surface, center, scale=1.0):
    cx, cy = center
    left_bottom = (cx - 20 * scale, cy + 40 * scale)
    right_bottom = (cx + 20 * scale, cy + 40 * scale)
    left_deck = (cx - 10 * scale, cy - 20 * scale)
    right_deck = (cx + 10 * scale, cy - 20 * scale)
    control = (cx, cy - 60 * scale)
    bow_points = []
    num_points = 20
    for i in range(num_points + 1):
        tt = i / num_points
        x = (1 - tt)**2 * left_deck[0] + 2 * (1 - tt) * tt * control[0] + tt**2 * right_deck[0]
        y = (1 - tt)**2 * left_deck[1] + 2 * (1 - tt) * tt * control[1] + tt**2 * right_deck[1]
        bow_points.append((x, y))
    boat_points = [left_bottom] + bow_points + [right_bottom]
    pygame.draw.polygon(surface, BLACK, boat_points)
    pygame.draw.polygon(surface, GRAY, boat_points, 2)

def render_two_line_label(surface, text_line1, text_line2, center, font, color, line_spacing=6):
    """Render two centered lines of text."""
    l1 = font.render(text_line1, True, color)
    l2 = font.render(text_line2, True, color)

    total_h = l1.get_height() + line_spacing + l2.get_height()
    top_y = center[1] - total_h // 2

    surface.blit(l1, l1.get_rect(center=(center[0], top_y + l1.get_height() // 2)))
    surface.blit(l2, l2.get_rect(center=(center[0], top_y + l1.get_height() + line_spacing + l2.get_height() // 2)))


def draw_rudder_gauge(surface, center, radius, needle_angle_deg):
    """
    Trim Angle gauge rotated 90 degrees CCW (graphics + needle),
    with a single "TRIM" label placed cleanly in the left-side open area.
    """
    cx, cy = center

    # ---- 1) Draw the gauge to an offscreen surface centered at (radius, radius)
    gauge_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    gauge_center = (radius, radius)

    # Base circle
    pygame.draw.circle(gauge_surf, BLACK, gauge_center, radius)

    # Arcs + ticks
    draw_dotted_arc(gauge_surf, gauge_center, radius - 20, 30, 90, 4, 3, GREEN)
    draw_dotted_arc(gauge_surf, gauge_center, radius - 20, 90, 150, 4, 3, RED)

    for deg in [30, 60, 90, 120, 150]:
        theta = math.radians(deg)
        x1 = gauge_center[0] + math.cos(theta) * (radius - 35)
        y1 = gauge_center[1] + math.sin(theta) * (radius - 35)
        x2 = gauge_center[0] + math.cos(theta) * (radius - 50)
        y2 = gauge_center[1] + math.sin(theta) * (radius - 50)
        pygame.draw.line(gauge_surf, GRAY, (x1, y1), (x2, y2), 3)

    # Boat shape
    draw_boat_shape(gauge_surf, gauge_center, scale=2.0)

    # Needle (movement stays the same)
    offset_degrees = -90
    needle_theta = math.radians(needle_angle_deg + offset_degrees)
    needle_length = radius * 0.7
    nx = gauge_center[0] + math.cos(needle_theta) * needle_length
    ny = gauge_center[1] + math.sin(needle_theta) * needle_length
    pygame.draw.line(gauge_surf, RED, gauge_center, (nx, ny), 4)

    pygame.draw.circle(gauge_surf, BLACK, gauge_center, 12)
    pygame.draw.circle(gauge_surf, GRAY, gauge_center, 12, 2)

    # ---- 2) Rotate the entire gauge 90° CCW
    rotated = pygame.transform.rotate(gauge_surf, 90)
    rot_rect = rotated.get_rect(center=center)
    surface.blit(rotated, rot_rect.topleft)

    # ---- 3) Draw readable "TRIM" label in the clean left-side area
    # Left edge of the black circle (screen coords)
    circle_left_x = cx - radius

    # Approx left edge of the rotated boat nose area (screen coords)
    # Tweak this factor if you want the TRIM position to shift slightly.
    boat_nose_left_x = rot_rect.left + int(rot_rect.width * 0.33)

    # Center TRIM between circle left edge and boat nose left edge
    trim_center_x = (circle_left_x + boat_nose_left_x) // 2
    trim_center = (trim_center_x, cy)

    trim_text = heading_font.render("TRIM", True, WHITE)
    surface.blit(trim_text, trim_text.get_rect(center=trim_center))



def draw_rpm_gauge(surface, center, radius, rpm_value):
    cx, cy = center
    needle_angle = map_value(rpm_value, 0, 6000, 150, 390)
    pygame.draw.circle(surface, BLACK, center, radius)
    draw_dotted_arc(surface, center, radius - 20, 150, 375, 4, 3, GREEN)
    draw_dotted_arc(surface, center, radius - 20, 10, 30, 4, 3, RED)
    major_ticks = [150, 190, 230, 270, 310, 350, 390]
    tick_labels = ["0", "10", "20", "30", "40", "50", "60"]
    tick_font = pygame.font.SysFont("Arial", int(smaller_dim * 0.03))
    for i, deg in enumerate(major_ticks):
        theta = math.radians(deg)
        x1 = cx + math.cos(theta) * (radius - 35)
        y1 = cy + math.sin(theta) * (radius - 35)
        x2 = cx + math.cos(theta) * (radius - 50)
        y2 = cy + math.sin(theta) * (radius - 50)
        pygame.draw.line(surface, GRAY, (x1, y1), (x2, y2), 3)
        text_x = cx + math.cos(theta) * (radius - 70)
        text_y = cy + math.sin(theta) * (radius - 70)
        label = tick_font.render(tick_labels[i], True, WHITE)
        surface.blit(label, label.get_rect(center=(text_x, text_y)))
    for deg in [170, 210, 250, 290, 330, 370]:
        theta = math.radians(deg)
        x1 = cx + math.cos(theta) * (radius - 35)
        y1 = cy + math.sin(theta) * (radius - 35)
        x2 = cx + math.cos(theta) * (radius - 50)
        y2 = cy + math.sin(theta) * (radius - 50)
        pygame.draw.line(surface, GRAY, (x1, y1), (x2, y2), 1)
    needle_theta = math.radians(needle_angle)
    nx = cx + math.cos(needle_theta) * radius * 0.7
    ny = cy + math.sin(needle_theta) * radius * 0.7
    pygame.draw.line(surface, RED, (cx, cy), (nx, ny), 4)
    pygame.draw.circle(surface, BLACK, center, 12)
    pygame.draw.circle(surface, GRAY, center, 12, 2)
    rpm_heading = heading_font.render("Engine RPM", True, WHITE)
    surface.blit(rpm_heading, rpm_heading.get_rect(center=(cx, cy + radius - 80)))
    small_font = pygame.font.SysFont("Arial", int(smaller_dim * 0.03))
    x100_label = small_font.render("x100RPM", True, WHITE)
    surface.blit(x100_label, x100_label.get_rect(center=(cx, cy - 30)))

def draw_navtronics_box(surface):
    font = pygame.font.SysFont("Arial", int(smaller_dim * 0.035), bold=True)
    line1 = font.render("STROHOFER", True, BLACK)
    line2 = font.render("NAVTRONICS", True, BLACK)
    padding = 10
    spacing = int(padding * 0.7)
    width = max(line1.get_width(), line2.get_width()) + 6 * padding
    height = line1.get_height() + line2.get_height() + spacing + 2 * padding
    box_surface = pygame.Surface((width, height))
    box_surface.fill(BACKGROUND_COLOR)
    pygame.draw.rect(box_surface, BLACK, box_surface.get_rect(), 10, border_radius=12)
    box_surface.blit(line1, ((width - line1.get_width()) // 2, padding))
    box_surface.blit(line2, ((width - line2.get_width()) // 2, padding + line1.get_height() + spacing))
    center_x = (GAUGE_TOP_CENTER[0] + GAUGE_BOTTOM_CENTER[0]) // 2
    center_y = (GAUGE_TOP_CENTER[1] + GAUGE_BOTTOM_CENTER[1]) // 2
    screen.blit(box_surface, (center_x - width // 2, center_y - height // 2))

def draw_fuel_and_shift_boxes(surface):
    box_width = 180
    box_height = 100
    corner_radius = 20
    value_font = pygame.font.SysFont("Arial", int(smaller_dim * 0.06), bold=True)
    label_font = pygame.font.SysFont("Arial", int(smaller_dim * 0.035), bold=True)
    center_y = (GAUGE_TOP_CENTER[1] + GAUGE_BOTTOM_CENTER[1]) // 2
    center_x = GAUGE_TOP_CENTER[0]

    # Fuel box
    fuel_rect = pygame.Rect(center_x - box_width * 2, center_y - box_height // 2, box_width, box_height)
    pygame.draw.rect(surface, BLACK, fuel_rect, border_radius=corner_radius)

    fuel_str = f"{fuel_consumption:.1f}" if fuel_consumption is not None else "-"
    fuel_text = value_font.render(fuel_str, True, WHITE)
    surface.blit(fuel_text, fuel_text.get_rect(center=(fuel_rect.left + box_width // 3, fuel_rect.centery)))

    gal_label = label_font.render("Gal", True, WHITE)
    hr_label = label_font.render("Hr", True, WHITE)
    surface.blit(gal_label, gal_label.get_rect(center=(fuel_rect.right - 30, fuel_rect.centery - 15)))
    surface.blit(hr_label, hr_label.get_rect(center=(fuel_rect.right - 30, fuel_rect.centery + 15)))

    # Shift box
    shift_rect = pygame.Rect(center_x + box_width, center_y - box_height // 2, box_width, box_height)
    pygame.draw.rect(surface, BLACK, shift_rect, border_radius=corner_radius)

    gear_lookup = {1: "R", 2: "N", 3: "F"}
    gear_letter = gear_lookup.get(shift_indicator, "-")
    gear_color = (252, 241, 7) if shift_indicator == 2 else WHITE
    gear_text = value_font.render(gear_letter, True, gear_color)
    surface.blit(gear_text, gear_text.get_rect(center=shift_rect.center))

# Boot into a safe no-data UI until proven otherwise
set_no_data_state()
last_good_frame_time = time.monotonic()

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
            running = False
    if GPIO.input(BUTTON_PIN) == GPIO.LOW:
        running = False

    # Serial handling (survives Arduino off/unplugged)
    try_open_serial()
    process_serial_data()

    # If data is stale (or never arrived), force no-data UI
    now = time.monotonic()
    if now - last_good_frame_time > DATA_STALE_SECONDS:
        set_no_data_state()

    screen.fill(BACKGROUND_COLOR)
    t = pygame.time.get_ticks()
    draw_water_waves(screen, t)

    draw_rudder_gauge(screen, GAUGE_TOP_CENTER, GAUGE_RADIUS, rudder_angle)
    draw_rpm_gauge(screen, GAUGE_BOTTOM_CENTER, GAUGE_RADIUS, smoothed_engine_rpm)
    draw_navtronics_box(screen)
    draw_fuel_and_shift_boxes(screen)

    pygame.display.flip()
    clock.tick(60)

subprocess.Popen(["/usr/bin/wf-panel-pi"])
close_serial()
pygame.quit()
GPIO.cleanup()

