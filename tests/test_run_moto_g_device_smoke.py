from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

import pytest
import scripts.run_moto_g_device_smoke as smoke
from scripts.run_moto_g_device_smoke import (
    CommandResult,
    DeviceSmokeStep,
    StepStatus,
    build_report,
    command_window_contains,
    main,
    render_json,
    render_text,
    timeline_command_occurrences,
    verify_device_map_surface,
    verify_home_surface,
)
from scripts.verify_moto_g_readiness import DEBUG_APK_RELATIVE_PATH

SERIAL = "ZY32LBQLMQ"
TEST_MEMORY_TEXT = "goffy memory smoke test 20260722"
TEST_MEMORY_COMMAND = smoke.memory_remember_command(TEST_MEMORY_TEXT)
ADB_DEVICES = (
    "List of devices attached\n"
    f"{SERIAL} device usb:2-1.2 product:kansas_g_sys model:moto_g___2025 device:kansas\n"
)

BASE_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="GOFFY" class="android.widget.TextView" enabled="true" '
        'bounds="[60,40][240,100]" />',
        '  <node text="GOFFY LITE" class="android.widget.TextView" enabled="true" '
        'bounds="[540,40][690,88]" />',
        '  <node text="SETTINGS" content-desc="Open Android Settings. GOFFY launches only '
        'the system settings screen from this button." class="android.widget.TextView" '
        'enabled="true" bounds="[540,96][690,154]" />',
        '  <node text="" content-desc="GOFFY orb state: IDLE. Execution target: PHONE. '
        'Task phase: NO ACTIVE TASK." class="android.view.View" enabled="true" '
        'bounds="[277,180][443,346]" />',
        '  <node text="LOOP / IDLE" class="android.widget.TextView" enabled="true" '
        'bounds="[260,360][360,400]" />',
        '  <node text="MAC LINK" class="android.widget.TextView" enabled="true" '
        'bounds="[60,430][160,470]" />',
        '  <node text="EXECUTION TARGET" class="android.widget.TextView" enabled="true" '
        'bounds="[220,430][360,470]" />',
        '  <node text="DOCK MODE" class="android.widget.TextView" enabled="true" '
        'bounds="[520,430][660,470]" />',
        '  <node text="HOME SHELL" class="android.widget.TextView" enabled="true" '
        'bounds="[60,500][220,540]" />',
        '  <node text="STATUS UNKNOWN / CHECK PHONE INFO" class="android.widget.TextView" '
        'enabled="true" bounds="[60,550][460,590]" />',
        '  <node text="CHECK" class="android.widget.TextView" enabled="true" '
        'bounds="[520,525][650,590]" />',
        '  <node text="DEVICE MAP" class="android.widget.TextView" enabled="true" '
        'bounds="[60,630][220,670]" />',
        '  <node text="PHONE ENGINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,692][240,732]" />',
        '  <node text="MAC HUB" class="android.widget.TextView" enabled="true" '
        'bounds="[60,748][180,788]" />',
        '  <node text="MCP REGISTRY" class="android.widget.TextView" enabled="true" '
        'bounds="[60,804][240,844]" />',
        '  <node text="LOCAL MODEL" class="android.widget.TextView" enabled="true" '
        'bounds="[60,860][240,900]" />',
        '  <node text="Ask GOFFY to do something" class="android.widget.TextView" '
        'enabled="true" bounds="[60,910][420,950]" />',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,1000][660,1140]" />',
        '  <node text="MIC" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1170][130,1210]" />',
        '  <node text="CAM" class="android.widget.TextView" enabled="true" '
        'bounds="[150,1170][220,1210]" />',
        '  <node text="OCR" class="android.widget.TextView" enabled="true" '
        'bounds="[240,1170][310,1210]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1200][660,1280]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1300][260,1340]" />',
        '  <node text="No actions yet. Every GOFFY step will appear here." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1350][660,1390]" />',
        "</hierarchy>",
    ]
)


DEVICE_MAP_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="DEVICE MAP" class="android.widget.TextView" enabled="true" '
        'bounds="[60,200][220,240]" />',
        '  <node text="PHONE ENGINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,330][260,370]" />',
        '  <node text="MAC HUB" class="android.widget.TextView" enabled="true" '
        'bounds="[60,440][220,480]" />',
        '  <node text="MCP REGISTRY" class="android.widget.TextView" enabled="true" '
        'bounds="[60,550][260,590]" />',
        '  <node text="LOCAL MODEL" class="android.widget.TextView" enabled="true" '
        'bounds="[60,660][260,700]" />',
        '  <node text="CLOUD" class="android.widget.TextView" enabled="true" '
        'bounds="[60,770][180,810]" />',
        "</hierarchy>",
    ]
)


ICON_SEND_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="check my battery level" class="android.widget.EditText" enabled="true" '
        'bounds="[60,510][660,650]" />',
        '  <node text="MIC" class="android.widget.TextView" enabled="true" '
        'bounds="[102,738][140,773]" />',
        '  <node text="" class="android.view.View" clickable="true" enabled="true" '
        'bounds="[588,671][672,839]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[63,924][185,966]" />',
        "</hierarchy>",
    ]
)


COMMAND_FIELD_ONLY_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,1454][660,1594]" />',
        "</hierarchy>",
    ]
)


COMMAND_FIELD_EMPTY_SEND_DISABLED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="" class="android.view.View" clickable="true" enabled="false" '
        'bounds="[588,1060][672,1228]" />',
        "</hierarchy>",
    ]
)


COMMAND_FIELD_EMPTY_SEND_ENABLED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        "</hierarchy>",
    ]
)


COMMAND_TYPED_DISABLED_SEND_WITH_ENABLED_WRAPPER_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="check my battery level" class="android.widget.EditText" '
        'enabled="true" bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="false" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="" class="android.view.View" clickable="true" enabled="true" '
        'bounds="[588,1060][672,1228]" />',
        "</hierarchy>",
    ]
)


TIMELINE_HEADER_ONLY_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        "</hierarchy>",
    ]
)


COMMAND_TYPED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="check my battery level" class="android.widget.EditText" '
        'enabled="true" bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        "</hierarchy>",
    ]
)


COMMAND_TYPED_SEND_OFFSCREEN_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="check my battery level" class="android.widget.EditText" '
        'enabled="true" bounds="[60,900][660,1040]" />',
        "</hierarchy>",
    ]
)


MAC_COMMAND_TYPED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="check my Mac status" class="android.widget.EditText" '
        'enabled="true" bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        "</hierarchy>",
    ]
)


MAC_PROCESS_COMMAND_TYPED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="What is running on my Mac" class="android.widget.EditText" '
        'enabled="true" bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        "</hierarchy>",
    ]
)


MAC_ROM_STATUS_COMMAND_TYPED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="Show GOFFY ROM status" class="android.widget.EditText" '
        'enabled="true" bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        "</hierarchy>",
    ]
)


TIMELINE_ONLY_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="Recorded battery status task" class="android.widget.TextView" '
        'enabled="true" bounds="[86,63][554,105]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[568,63][634,105]" />',
        '  <node text="PHONE  /  phone.battery.status  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[86,168][434,210]" />',
        "</hierarchy>",
    ]
)


HOME_TOP_ONLY_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="GOFFY" class="android.widget.TextView" enabled="true" '
        'bounds="[60,40][240,100]" />',
        '  <node text="DEVICE MAP" class="android.widget.TextView" enabled="true" '
        'bounds="[60,530][220,570]" />',
        "</hierarchy>",
    ]
)


STALE_PHONE_COMMAND_TIMELINE_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[63,10][185,52]" />',
        '  <node text="check my battery level" class="android.widget.TextView" '
        'enabled="true" bounds="[86,63][554,105]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[568,63][634,105]" />',
        '  <node text="PHONE  /  phone.battery.status  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[86,168][434,210]" />',
        '  <node text="Battery status matched the local tool contract." '
        'class="android.widget.TextView" enabled="true" bounds="[86,220][634,262]" />',
        "</hierarchy>",
    ]
)


PHONE_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        '  <node text="check my battery level" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1200][400,1240]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1200][650,1240]" />',
        '  <node text="PHONE  /  phone.battery.status  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1260][600,1300]" />',
        '  <node text="42%" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1320][160,1360]" />',
        '  <node text="Battery status matched the local tool contract." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1380][620,1420]" />',
        "</hierarchy>",
    ]
)


PHONE_UI_XML_WITH_STALE_AND_FRESH = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        '  <node text="check my battery level" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1200][400,1240]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1200][650,1240]" />',
        '  <node text="PHONE  /  phone.battery.status  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1260][600,1300]" />',
        '  <node text="42%" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1320][160,1360]" />',
        '  <node text="Battery status matched the local tool contract." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1380][620,1420]" />',
        '  <node text="check my battery level" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1440][400,1480]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1440][650,1480]" />',
        '  <node text="PHONE  /  phone.battery.status  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1500][600,1540]" />',
        '  <node text="42%" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1560][160,1600]" />',
        '  <node text="Battery status matched the local tool contract." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1620][620,1660]" />',
        "</hierarchy>",
    ]
)


PHONE_UI_XML_FRESH_PENDING_THEN_STALE_SUCCESS = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        '  <node text="check my battery level" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1200][400,1240]" />',
        '  <node text="PENDING" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1200][650,1240]" />',
        '  <node text="PHONE  /  phone.battery.status  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1260][600,1300]" />',
        '  <node text="check my battery level" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1320][400,1360]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1320][650,1360]" />',
        '  <node text="PHONE  /  phone.battery.status  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1380][600,1420]" />',
        '  <node text="42%" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1440][160,1480]" />',
        '  <node text="Battery status matched the local tool contract." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1500][620,1540]" />',
        "</hierarchy>",
    ]
)


MAC_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        '  <node text="check my Mac status" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1200][400,1240]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1200][650,1240]" />',
        '  <node text="MAC  /  mac.system_info  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1260][600,1300]" />',
        '  <node text="Darwin / arm64" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1320][260,1360]" />',
        '  <node text="mac.system_info output matched the registered schema." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1380][620,1420]" />',
        "</hierarchy>",
    ]
)


MAC_PROCESS_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        '  <node text="What is running on my Mac" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1200][430,1240]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1200][650,1240]" />',
        '  <node text="MAC  /  mac.processes.list  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1260][600,1300]" />',
        '  <node text="MAC PROCESSES / 2" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1320][320,1360]" />',
        '  <node text="mac.processes.list output matched the registered schema." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1380][660,1420]" />',
        "</hierarchy>",
    ]
)


MAC_ROM_STATUS_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        '  <node text="Show GOFFY ROM status" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1200][430,1240]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1200][650,1240]" />',
        '  <node text="MAC  /  goffy.rom.status  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1260][600,1300]" />',
        '  <node text="GOFFY ROM-0 / AVAILABLE" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1320][360,1360]" />',
        '  <node text="goffy.rom.status output matched the registered schema." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1380][660,1420]" />',
        "</hierarchy>",
    ]
)


MEMORY_REMEMBER_COMMAND_TYPED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        f'  <node text="{TEST_MEMORY_COMMAND}" class="android.widget.EditText" '
        'enabled="true" bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        "</hierarchy>",
    ]
)


MEMORY_APPROVAL_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="Approve once" class="android.widget.TextView" enabled="true" '
        'bounds="[10,10][110,60]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,100][260,140]" />',
        f'  <node text="{TEST_MEMORY_COMMAND}" class="android.widget.TextView" '
        'enabled="true" bounds="[60,180][620,220]" />',
        '  <node text="AWAITING APPROVAL" class="android.widget.TextView" enabled="true" '
        'bounds="[500,180][690,220]" />',
        '  <node text="PHONE  /  phone.memory.remember  /  CONFIRM" '
        'class="android.widget.TextView" enabled="true" bounds="[60,240][660,280]" />',
        '  <node text="APPROVAL REQUIRED" class="android.widget.TextView" enabled="true" '
        'bounds="[60,300][320,340]" />',
        f'  <node text="Approve remembering this locally: {TEST_MEMORY_TEXT}" '
        'class="android.widget.TextView" enabled="true" bounds="[60,360][660,400]" />',
        '  <node text="Deny" class="android.widget.TextView" enabled="true" '
        'bounds="[430,420][500,470]" />',
        '  <node text="Approve once" class="android.widget.TextView" enabled="true" '
        'bounds="[520,420][680,500]" />',
        "</hierarchy>",
    ]
)


MEMORY_REMEMBER_VERIFIED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,100][260,140]" />',
        f'  <node text="{TEST_MEMORY_COMMAND}" class="android.widget.TextView" '
        'enabled="true" bounds="[60,180][620,220]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,180][690,220]" />',
        '  <node text="MEMORY SAVED / #1" class="android.widget.TextView" enabled="true" '
        'bounds="[60,240][320,280]" />',
        f'  <node text="{TEST_MEMORY_TEXT}" class="android.widget.TextView" enabled="true" '
        'bounds="[60,300][420,340]" />',
        '  <node text="PHONE  /  phone.memory.remember  /  CONFIRM" '
        'class="android.widget.TextView" enabled="true" bounds="[60,360][660,400]" />',
        "</hierarchy>",
    ]
)


MEMORY_LIST_COMMAND_TYPED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        f'  <node text="{smoke.DEFAULT_MEMORY_LIST_COMMAND}" class="android.widget.EditText" '
        'enabled="true" bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        "</hierarchy>",
    ]
)


MEMORY_LIST_VERIFIED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,100][260,140]" />',
        f'  <node text="{smoke.DEFAULT_MEMORY_LIST_COMMAND}" class="android.widget.TextView" '
        'enabled="true" bounds="[60,180][620,220]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,180][690,220]" />',
        '  <node text="MEMORIES / 1" class="android.widget.TextView" enabled="true" '
        'bounds="[60,240][320,280]" />',
        f'  <node text="#1 / {TEST_MEMORY_TEXT}" class="android.widget.TextView" '
        'enabled="true" bounds="[60,300][520,340]" />',
        '  <node text="PHONE  /  phone.memory.list  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,360][660,400]" />',
        "</hierarchy>",
    ]
)


MEMORY_LIST_EMPTY_WITH_OLDER_REMEMBER_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,100][260,140]" />',
        f'  <node text="{smoke.DEFAULT_MEMORY_LIST_COMMAND}" class="android.widget.TextView" '
        'enabled="true" bounds="[60,180][620,220]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,180][690,220]" />',
        '  <node text="MEMORIES / 0" class="android.widget.TextView" enabled="true" '
        'bounds="[60,240][320,280]" />',
        '  <node text="PHONE  /  phone.memory.list  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,300][660,340]" />',
        f'  <node text="{TEST_MEMORY_COMMAND}" class="android.widget.TextView" '
        'enabled="true" bounds="[60,420][620,460]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,420][690,460]" />',
        '  <node text="MEMORY SAVED / #1" class="android.widget.TextView" enabled="true" '
        'bounds="[60,480][320,520]" />',
        f'  <node text="{TEST_MEMORY_TEXT}" class="android.widget.TextView" enabled="true" '
        'bounds="[60,540][420,580]" />',
        '  <node text="PHONE  /  phone.memory.remember  /  CONFIRM" '
        'class="android.widget.TextView" enabled="true" bounds="[60,600][660,640]" />',
        "</hierarchy>",
    ]
)


DEBUG_SETUP_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="SECURE HUB LINK" class="android.widget.TextView" '
        'enabled="true" bounds="[60,13][205,55]" />',
        '  <node text="NOT CONFIGURED" class="android.widget.TextView" '
        'enabled="true" bounds="[60,55][233,97]" />',
        '  <node text="Hide" class="android.widget.TextView" enabled="true" '
        'bounds="[582,38][637,73]" />',
        '  <node text="ws://127.0.0.1:8787/ws/v1" '
        'class="android.widget.EditText" enabled="true" bounds="[60,301][660,413]" />',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,427][660,580]" />',
        '  <node text="Development bearer token" class="android.widget.TextView" '
        'enabled="true" bounds="[88,735][367,763]" />',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,776][660,871]" />',
        "</hierarchy>",
    ]
)


DEBUG_SETUP_WITH_COMMAND_INPUT_UI_XML = DEBUG_SETUP_UI_XML.replace(
    "</hierarchy>",
    '  <node text="" class="android.widget.EditText" enabled="true" '
    'bounds="[60,1449][660,1589]" />\n'
    "</hierarchy>",
)


DEBUG_TOKEN_FOCUSED_UI_XML = DEBUG_SETUP_UI_XML.replace(
    '  <node text="" class="android.widget.EditText" enabled="true" bounds="[60,776][660,871]" />',
    '  <node text="" class="android.widget.EditText" enabled="true" focused="true" '
    'bounds="[60,776][660,871]" />',
)


EXPANDED_SETUP_WITH_COMMAND_UI_XML = DEBUG_SETUP_UI_XML.replace(
    "</hierarchy>",
    '  <node text="" class="android.widget.EditText" enabled="true" '
    'password="false" bounds="[60,1200][660,1340]" />\n'
    '  <node text="Send" class="android.widget.TextView" enabled="true" '
    'bounds="[520,1400][660,1480]" />\n'
    "</hierarchy>",
)


DEBUG_LINK_BUTTON_UI_XML = DEBUG_SETUP_UI_XML.replace(
    "</hierarchy>",
    '  <node text="Debug link" class="android.widget.TextView" enabled="true" '
    'bounds="[485,890][618,925]" />\n'
    "</hierarchy>",
)


DEBUG_LINK_DISABLED_BUTTON_UI_XML = DEBUG_SETUP_UI_XML.replace(
    "</hierarchy>",
    '  <node text="" class="android.view.View" enabled="false" clickable="true" '
    'bounds="[443,870][660,954]">\n'
    '    <node text="Debug link" class="android.widget.TextView" enabled="true" '
    'bounds="[485,895][618,930]" />\n'
    "  </node>\n"
    "</hierarchy>",
)


DEBUG_LINK_CONFIGURED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="SECURE HUB LINK" class="android.widget.TextView" '
        'enabled="true" bounds="[60,13][205,55]" />',
        '  <node text="ws://127.0.0.1:8787/ws/v1" class="android.widget.TextView" '
        'enabled="true" bounds="[60,55][297,97]" />',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,175][660,315]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,336][660,420]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,505][260,545]" />',
        "</hierarchy>",
    ]
)


def adb_args(command: Sequence[str]) -> tuple[str, ...]:
    if len(command) >= 3 and command[1] == "-s":
        return tuple(command[3:])
    return tuple(command[1:])


def target_runner(command: Sequence[str]) -> CommandResult | None:
    args = tuple(command[1:])
    if args == ("devices", "-l"):
        return CommandResult(0, ADB_DEVICES, "")
    if adb_args(command) == ("shell", "getprop", "ro.product.model"):
        return CommandResult(0, "moto g - 2025\n", "")
    return None


def test_home_surface_smoke_accepts_required_os_shell_markers(tmp_path: Path) -> None:
    result = verify_home_surface(ui_xml=BASE_UI_XML, output_directory=tmp_path)

    assert result.status is StepStatus.OK
    assert result.name == "HOME surface smoke"
    assert result.artifact == "home-surface.xml"
    assert (tmp_path / "home-surface.xml").read_text(encoding="utf-8") == BASE_UI_XML


@pytest.mark.parametrize(
    "status",
    [
        "STATUS UNKNOWN / CHECK PHONE INFO",
        "DEFAULT HOME / GOFFY CONTROLS HOME",
        "AVAILABLE / CHOOSE GOFFY AS HOME",
        "NOT AVAILABLE / HOME INTENT MISSING",
    ],
)
def test_home_surface_smoke_accepts_each_home_setup_status(
    status: str,
    tmp_path: Path,
) -> None:
    ui_xml = BASE_UI_XML.replace("STATUS UNKNOWN / CHECK PHONE INFO", status)

    result = verify_home_surface(ui_xml=ui_xml, output_directory=tmp_path)

    assert result.status is StepStatus.OK


def test_home_surface_smoke_reports_missing_markers(tmp_path: Path) -> None:
    sparse_xml = "\n".join(
        [
            "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
            '<hierarchy rotation="0">',
            '  <node text="GOFFY" class="android.widget.TextView" enabled="true" '
            'bounds="[60,40][240,100]" />',
            "</hierarchy>",
        ]
    )

    result = verify_home_surface(ui_xml=sparse_xml, output_directory=tmp_path)

    assert result.status is StepStatus.FAIL
    assert result.artifact == "home-surface.xml"
    assert "GOFFY LITE" in result.detail


def test_home_surface_smoke_requires_home_setup_card(tmp_path: Path) -> None:
    missing_home_setup_xml = (
        BASE_UI_XML.replace(
            '  <node text="HOME SHELL" class="android.widget.TextView" enabled="true" '
            'bounds="[60,500][220,540]" />\n',
            "",
        )
        .replace(
            '  <node text="STATUS UNKNOWN / CHECK PHONE INFO" class="android.widget.TextView" '
            'enabled="true" bounds="[60,550][460,590]" />\n',
            "",
        )
        .replace(
            '  <node text="CHECK" class="android.widget.TextView" enabled="true" '
            'bounds="[520,525][650,590]" />\n',
            "",
        )
    )

    result = verify_home_surface(ui_xml=missing_home_setup_xml, output_directory=tmp_path)

    assert result.status is StepStatus.FAIL
    assert "HOME SHELL" in result.detail
    assert "HOME status" in result.detail
    assert "HOME CHECK" in result.detail


def test_home_surface_smoke_requires_exact_goffy_title(tmp_path: Path) -> None:
    missing_title_xml = BASE_UI_XML.replace(
        '  <node text="GOFFY" class="android.widget.TextView" enabled="true" '
        'bounds="[60,40][240,100]" />\n',
        "",
    )

    result = verify_home_surface(ui_xml=missing_title_xml, output_directory=tmp_path)

    assert result.status is StepStatus.FAIL
    assert "GOFFY title" in result.detail


def test_home_surface_smoke_rejects_offscreen_markers(tmp_path: Path) -> None:
    offscreen_xml = BASE_UI_XML.replace(
        'bounds="[540,40][690,88]"',
        'bounds="[540,1700][690,1760]"',
    )

    result = verify_home_surface(ui_xml=offscreen_xml, output_directory=tmp_path)

    assert result.status is StepStatus.FAIL
    assert "GOFFY LITE" in result.detail


def test_home_surface_smoke_allows_restored_timeline_history(tmp_path: Path) -> None:
    restored_xml = BASE_UI_XML.replace(
        "No actions yet. Every GOFFY step will appear here.",
        "check my battery level",
    )

    result = verify_home_surface(ui_xml=restored_xml, output_directory=tmp_path)

    assert result.status is StepStatus.OK


def test_home_surface_smoke_allows_command_surface_below_launch_viewport(
    tmp_path: Path,
) -> None:
    scrolled_below_viewport_xml = (
        BASE_UI_XML.replace('bounds="[60,810][420,850]"', 'bounds="[60,1810][420,1850]"')
        .replace('bounds="[60,900][660,1040]"', 'bounds="[60,1900][660,2040]"')
        .replace('bounds="[60,1070][130,1110]"', 'bounds="[60,2070][130,2110]"')
        .replace('bounds="[150,1070][220,1110]"', 'bounds="[150,2070][220,2110]"')
        .replace('bounds="[240,1070][310,1110]"', 'bounds="[240,2070][310,2110]"')
        .replace('bounds="[60,1200][260,1240]"', 'bounds="[60,2200][260,2240]"')
    )

    result = verify_home_surface(ui_xml=scrolled_below_viewport_xml, output_directory=tmp_path)

    assert result.status is StepStatus.OK


def test_device_map_viewport_smoke_accepts_required_node_labels(tmp_path: Path) -> None:
    result = verify_device_map_surface(ui_xml=DEVICE_MAP_UI_XML, output_directory=tmp_path)

    assert result.status is StepStatus.OK
    assert result.name == "Device map viewport smoke"
    assert result.artifact == "device-map.xml"
    assert (tmp_path / "device-map.xml").read_text(encoding="utf-8") == DEVICE_MAP_UI_XML


def test_device_map_viewport_smoke_reports_missing_node_labels(tmp_path: Path) -> None:
    missing_mac_xml = DEVICE_MAP_UI_XML.replace(
        '  <node text="MAC HUB" class="android.widget.TextView" enabled="true" '
        'bounds="[60,440][220,480]" />\n',
        "",
    )

    result = verify_device_map_surface(ui_xml=missing_mac_xml, output_directory=tmp_path)

    assert result.status is StepStatus.FAIL
    assert "MAC HUB" in result.detail


def test_plan_mode_never_executes_device_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "", "")

    report = build_report(root=tmp_path, runner=runner, include_mac=True)

    assert report.ok
    assert not report.executed
    assert seen == []
    assert all(step.status is StepStatus.PLANNED for step in report.steps)
    assert report.mac_command == smoke.DEFAULT_MAC_COMMAND


def test_plan_mode_includes_memory_smoke_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(root=tmp_path, include_memory=True)

    step_names = [step.name for step in report.steps]
    assert report.ok
    assert not report.executed
    assert "PHONE memory remember smoke" in step_names
    assert "PHONE memory list smoke" in step_names
    assert all(step.status is StepStatus.PLANNED for step in report.steps)


def test_execute_requires_explicit_device_mutation_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(root=tmp_path, execute=True, trusted_root=tmp_path)

    assert not report.ok
    assert not report.executed
    assert report.steps[0].detail == "missing explicit --confirm-device-mutation"


def test_execute_blocks_missing_debug_apk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert {step.detail for step in report.steps} == {"android/debug APK missing"}


def test_execute_rejects_non_smoke_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        phone_command="turn on flashlight",
        mac_command="open calculator",
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert {step.detail for step in report.steps} == {
        "execute mode only supports the fixed PHONE smoke command",
        "execute mode only supports the fixed MAC smoke commands",
    }


def test_execute_requires_single_or_explicit_moto_g_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        if tuple(command[1:]) == ("devices", "-l"):
            return CommandResult(
                0,
                "List of devices attached\n"
                "one device model:moto_g___2025\n"
                "two device model:moto_g___2025\n",
                "",
            )
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert report.steps == (
        DeviceSmokeStep(
            name="Verify Moto G target",
            status=StepStatus.FAIL,
            command=(str(adb), "devices", "-l"),
            detail="multiple authorized devices",
            remediation="Connect exactly one Moto G or pass --device-serial.",
        ),
    )


def test_execute_rejects_non_moto_g_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        if tuple(command[1:]) == ("devices", "-l"):
            return CommandResult(0, "List of devices attached\npixel device model:Pixel_9\n", "")
        if adb_args(command) == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "Pixel 9\n", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert report.steps[0].detail == "connected device is not the approved Moto G target"


def test_collapse_setup_card_does_not_skip_when_command_field_visible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    ui_outputs = iter((EXPANDED_SETUP_WITH_COMMAND_UI_XML, BASE_UI_XML))
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, BASE_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.collapse_setup_card_if_expanded(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
    )

    assert result.status is StepStatus.OK
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "tap",
        "609",
        "55",
    ) in seen


def test_restore_home_top_viewport_uses_extended_bounded_swipes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            return CommandResult(0, BASE_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.restore_home_top_viewport(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        output_directory=tmp_path,
    )

    assert result.status is StepStatus.OK
    restore_swipes = [
        command
        for command in seen
        if adb_args(command) == ("shell", "input", "swipe", "360", "650", "360", "1450", "450")
    ]
    assert len(restore_swipes) == len(smoke.HOME_TOP_RESTORE_SWIPES)


def test_execute_runs_fixed_setup_launch_and_phone_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)
    monkeypatch.setattr(
        smoke,
        "capture_screenshot",
        lambda **kwargs: DeviceSmokeStep(
            name="Capture screenshot",
            status=StepStatus.OK,
            artifact="final.png",
        ),
    )
    seen: list[tuple[str, ...]] = []
    cat_calls = 0

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal cat_calls
        seen.append(tuple(command))
        target = target_runner(command)
        if target is not None:
            return target
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            cat_calls += 1
            if cat_calls == 4:
                return CommandResult(0, DEVICE_MAP_UI_XML, "")
            if cat_calls == 5:
                return CommandResult(0, BASE_UI_XML, "")
            if cat_calls == 6:
                return CommandResult(0, COMMAND_TYPED_UI_XML, "")
            if cat_calls >= 7:
                return CommandResult(0, PHONE_UI_XML, "")
            return CommandResult(0, BASE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(0, "1234\n", "")
        if adb_args(command) == ("logcat", "-d", "--pid", "1234", "-t", "200"):
            return CommandResult(0, "goffy log\n", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert report.executed
    assert (tmp_path / "artifacts" / "home-surface.xml").is_file()
    assert (tmp_path / "artifacts" / "phone-command.xml").is_file()
    assert (tmp_path / "artifacts" / "goffy-logcat.txt").read_text(
        encoding="utf-8"
    ) == "goffy log\n"
    assert (str(adb), "-s", SERIAL, "reverse", "tcp:8787", "tcp:8787") in seen
    assert (str(adb), "-s", SERIAL, "install", "-r", str(apk)) in seen
    assert (str(adb), "-s", SERIAL, "shell", "am", "force-stop", smoke.PACKAGE_NAME) in seen
    assert (str(adb), "-s", SERIAL, "shell", "am", "start", "-W", "-n", smoke.MAIN_ACTIVITY) in seen
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "text",
        "check%smy%sbattery%slevel",
    ) in seen
    assert (str(adb), "-s", SERIAL, "logcat", "-d", "--pid", "1234", "-t", "200") in seen


def test_execute_runs_opt_in_memory_smoke_without_forget_all(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)
    monkeypatch.setattr(
        smoke,
        "capture_screenshot",
        lambda **kwargs: DeviceSmokeStep(
            name="Capture screenshot",
            status=StepStatus.OK,
            artifact="final.png",
        ),
    )
    seen: list[tuple[str, ...]] = []
    cat_calls = 0

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal cat_calls
        seen.append(tuple(command))
        target = target_runner(command)
        if target is not None:
            return target
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            cat_calls += 1
            if cat_calls < 4:
                return CommandResult(0, BASE_UI_XML, "")
            outputs = {
                4: DEVICE_MAP_UI_XML,
                5: BASE_UI_XML,
                6: COMMAND_TYPED_UI_XML,
                7: PHONE_UI_XML,
                8: BASE_UI_XML,
                9: MEMORY_REMEMBER_COMMAND_TYPED_UI_XML,
                10: MEMORY_APPROVAL_UI_XML,
                11: MEMORY_APPROVAL_UI_XML,
                12: MEMORY_REMEMBER_VERIFIED_UI_XML,
                13: BASE_UI_XML,
                14: BASE_UI_XML,
                15: MEMORY_LIST_COMMAND_TYPED_UI_XML,
                16: MEMORY_LIST_VERIFIED_UI_XML,
            }
            return CommandResult(0, outputs.get(cat_calls, MEMORY_LIST_VERIFIED_UI_XML), "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(0, "1234\n", "")
        if adb_args(command) == ("logcat", "-d", "--pid", "1234", "-t", "200"):
            return CommandResult(0, "goffy log\n", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_memory=True,
        memory_text=TEST_MEMORY_TEXT,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert report.executed
    assert any(step.name == "PHONE memory remember smoke" for step in report.steps)
    assert any(step.name == "PHONE memory list smoke" for step in report.steps)
    assert (tmp_path / "artifacts" / "phone-memory-remember.xml").is_file()
    assert (tmp_path / "artifacts" / "phone-memory-list.xml").is_file()
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "tap",
        "600",
        "460",
    ) in seen
    assert all("forget" not in " ".join(command).casefold() for command in seen)


def test_stale_ui_does_not_pass_without_fresh_command_card(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)
    monkeypatch.setattr(
        smoke,
        "capture_screenshot",
        lambda **kwargs: DeviceSmokeStep(name="Capture screenshot", status=StepStatus.OK),
    )

    cat_calls = 0

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal cat_calls
        target = target_runner(command)
        if target is not None:
            return target
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            cat_calls += 1
            if cat_calls <= 3:
                return CommandResult(0, BASE_UI_XML, "")
            if cat_calls == 4:
                return CommandResult(0, DEVICE_MAP_UI_XML, "")
            if cat_calls == 5:
                return CommandResult(0, PHONE_UI_XML, "")
            if cat_calls == 6:
                return CommandResult(0, COMMAND_TYPED_UI_XML, "")
            return CommandResult(0, PHONE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
        wait_timeout_seconds=1,
    )

    assert not report.ok
    assert any(
        step.name == "PHONE command smoke"
        and step.status is StepStatus.FAIL
        and "fresh command card" in step.detail
        for step in report.steps
    )


def test_submit_command_reveals_send_button_with_bounded_scroll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            COMMAND_FIELD_ONLY_UI_XML,
            COMMAND_TYPED_SEND_OFFSCREEN_UI_XML,
            COMMAND_TYPED_UI_XML,
            PHONE_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=5,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%", "Battery status matched the local tool contract."),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.OK
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "swipe",
        "360",
        "1450",
        "360",
        "650",
        "450",
    ) in seen
    assert (output_directory / "phone-command.xml").is_file()


def test_submit_command_reveals_input_below_launch_viewport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            HOME_TOP_ONLY_UI_XML,
            BASE_UI_XML,
            COMMAND_TYPED_UI_XML,
            PHONE_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=5,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%", "Battery status matched the local tool contract."),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.OK
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "swipe",
        "360",
        "1450",
        "360",
        "650",
        "450",
    ) in seen


def test_submit_command_falls_back_to_keyevents_when_adb_text_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            BASE_UI_XML,
            COMMAND_FIELD_EMPTY_SEND_DISABLED_UI_XML,
            COMMAND_TYPED_UI_XML,
            PHONE_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=5,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%"),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.OK
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "keyevent",
        "KEYCODE_C",
    ) in seen
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "keyevent",
        "KEYCODE_SPACE",
    ) in seen
    assert (output_directory / "phone-command-before-fallback.xml").is_file()
    assert (output_directory / "phone-command-after-fallback.xml").is_file()


def test_submit_command_does_not_tap_send_when_command_text_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            BASE_UI_XML,
            COMMAND_FIELD_EMPTY_SEND_ENABLED_UI_XML,
            COMMAND_FIELD_EMPTY_SEND_ENABLED_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, COMMAND_FIELD_EMPTY_SEND_ENABLED_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=5,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%"),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.FAIL
    assert result.detail == "command text was not entered after adb text and keyevent fallback"
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "tap",
        "590",
        "1140",
    ) not in seen


def test_find_send_control_fails_closed_for_disabled_explicit_send() -> None:
    command_field = smoke.find_command_field(
        COMMAND_TYPED_DISABLED_SEND_WITH_ENABLED_WRAPPER_UI_XML
    )

    assert command_field is not None
    assert (
        smoke.find_send_control(
            COMMAND_TYPED_DISABLED_SEND_WITH_ENABLED_WRAPPER_UI_XML,
            command_field=command_field,
        )
        is None
    )


def test_find_send_control_uses_stable_submit_description() -> None:
    xml = "\n".join(
        [
            "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
            '<hierarchy rotation="0">',
            '  <node text="check my battery level" class="android.widget.EditText" '
            'enabled="true" clickable="true" bounds="[60,900][660,1040]" />',
            '  <node text="" content-desc="Submit GOFFY command" class="android.view.View" '
            'enabled="true" clickable="true" bounds="[520,1100][660,1180]" />',
            "</hierarchy>",
        ]
    )
    command_field = smoke.find_command_field(xml)

    assert command_field is not None
    send = smoke.find_send_control(xml, command_field=command_field)
    assert send is not None
    assert send.content_desc == "Submit GOFFY command"


def test_submit_command_reveals_timeline_after_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            BASE_UI_XML,
            COMMAND_TYPED_UI_XML,
            COMMAND_FIELD_EMPTY_SEND_DISABLED_UI_XML,
            COMMAND_FIELD_EMPTY_SEND_DISABLED_UI_XML,
            COMMAND_FIELD_EMPTY_SEND_DISABLED_UI_XML,
            COMMAND_FIELD_EMPTY_SEND_DISABLED_UI_XML,
            COMMAND_FIELD_EMPTY_SEND_DISABLED_UI_XML,
            PHONE_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=5,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%"),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.OK
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "swipe",
        "360",
        "1450",
        "360",
        "650",
        "450",
    ) in seen


def test_submit_command_reveals_fresh_card_when_timeline_header_is_visible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            BASE_UI_XML,
            COMMAND_TYPED_UI_XML,
            TIMELINE_HEADER_ONLY_UI_XML,
            TIMELINE_HEADER_ONLY_UI_XML,
            TIMELINE_HEADER_ONLY_UI_XML,
            TIMELINE_HEADER_ONLY_UI_XML,
            TIMELINE_HEADER_ONLY_UI_XML,
            PHONE_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=5,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%"),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.OK
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "swipe",
        "360",
        "1450",
        "360",
        "650",
        "450",
    ) in seen


def test_submit_command_recovers_command_input_from_timeline_viewport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            STALE_PHONE_COMMAND_TIMELINE_UI_XML,
            STALE_PHONE_COMMAND_TIMELINE_UI_XML,
            STALE_PHONE_COMMAND_TIMELINE_UI_XML,
            STALE_PHONE_COMMAND_TIMELINE_UI_XML,
            BASE_UI_XML,
            COMMAND_TYPED_UI_XML,
            PHONE_UI_XML_WITH_STALE_AND_FRESH,
        )
    )
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML_WITH_STALE_AND_FRESH, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=5,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%", "Battery status matched the local tool contract."),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.OK
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "swipe",
        "360",
        "650",
        "360",
        "1450",
        "450",
    ) in seen


def test_submit_command_does_not_accept_stale_command_after_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            STALE_PHONE_COMMAND_TIMELINE_UI_XML,
            BASE_UI_XML,
            COMMAND_TYPED_UI_XML,
            PHONE_UI_XML,
        )
    )

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=1,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%", "Battery status matched the local tool contract."),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.FAIL
    assert "fresh command card" in result.detail


def test_submit_command_does_not_borrow_markers_from_stale_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            STALE_PHONE_COMMAND_TIMELINE_UI_XML,
            BASE_UI_XML,
            COMMAND_TYPED_UI_XML,
            PHONE_UI_XML_FRESH_PENDING_THEN_STALE_SUCCESS,
        )
    )

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML_FRESH_PENDING_THEN_STALE_SUCCESS, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=1,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%", "Battery status matched the local tool contract."),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.FAIL
    assert "fresh verified command card" in result.detail


def test_submit_command_requires_newest_matching_card_when_baseline_undercounts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            TIMELINE_ONLY_UI_XML,
            BASE_UI_XML,
            COMMAND_TYPED_UI_XML,
            PHONE_UI_XML_FRESH_PENDING_THEN_STALE_SUCCESS,
        )
    )

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML_FRESH_PENDING_THEN_STALE_SUCCESS, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=1,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%", "Battery status matched the local tool contract."),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.FAIL
    assert "fresh verified command card" in result.detail


def test_submit_command_taps_icon_only_send_control(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter((ICON_SEND_UI_XML, ICON_SEND_UI_XML, PHONE_UI_XML))
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=5,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%", "Battery status matched the local tool contract."),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.OK
    assert (str(adb), "-s", SERIAL, "shell", "input", "tap", "630", "699") in seen


def test_include_mac_requires_mac_visible_markers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)
    monkeypatch.setattr(
        smoke,
        "capture_screenshot",
        lambda **kwargs: DeviceSmokeStep(
            name="Capture screenshot",
            status=StepStatus.OK,
            artifact="final.png",
        ),
    )
    submitted_command: str | None = None
    result_ready: str | None = None
    device_map_revealed = False

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal device_map_revealed, result_ready, submitted_command
        target = target_runner(command)
        if target is not None:
            return target
        if (
            adb_args(command) == ("shell", "input", "swipe", "360", "1450", "360", "900", "350")
            and submitted_command is None
        ):
            device_map_revealed = True
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("shell", "input", "text", "check%smy%sbattery%slevel"):
            submitted_command = "phone"
            result_ready = None
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("shell", "input", "text", "check%smy%sMac%sstatus"):
            submitted_command = "mac"
            result_ready = None
            return CommandResult(0, "ok", "")
        if (
            adb_args(command)[:3] == ("shell", "input", "tap")
            and submitted_command is not None
            and result_ready is None
        ):
            result_ready = submitted_command
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            if device_map_revealed:
                device_map_revealed = False
                return CommandResult(0, DEVICE_MAP_UI_XML, "")
            if result_ready == "mac":
                return CommandResult(0, MAC_UI_XML, "")
            if result_ready == "phone":
                return CommandResult(0, PHONE_UI_XML, "")
            if submitted_command == "mac":
                return CommandResult(0, MAC_COMMAND_TYPED_UI_XML, "")
            if submitted_command == "phone":
                return CommandResult(0, COMMAND_TYPED_UI_XML, "")
            return CommandResult(0, BASE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert any(
        step.name == "MAC command smoke" and step.status is StepStatus.OK for step in report.steps
    )


def test_include_mac_can_smoke_process_list_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)
    monkeypatch.setattr(
        smoke,
        "capture_screenshot",
        lambda **kwargs: DeviceSmokeStep(
            name="Capture screenshot",
            status=StepStatus.OK,
            artifact="final.png",
        ),
    )
    submitted_command: str | None = None
    result_ready: str | None = None
    device_map_revealed = False

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal device_map_revealed, result_ready, submitted_command
        target = target_runner(command)
        if target is not None:
            return target
        if (
            adb_args(command) == ("shell", "input", "swipe", "360", "1450", "360", "900", "350")
            and submitted_command is None
        ):
            device_map_revealed = True
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("shell", "input", "text", "check%smy%sbattery%slevel"):
            submitted_command = "phone"
            result_ready = None
            return CommandResult(0, "ok", "")
        if adb_args(command) == (
            "shell",
            "input",
            "text",
            "What%sis%srunning%son%smy%sMac",
        ):
            submitted_command = "mac-process"
            result_ready = None
            return CommandResult(0, "ok", "")
        if (
            adb_args(command)[:3] == ("shell", "input", "tap")
            and submitted_command is not None
            and result_ready is None
        ):
            result_ready = submitted_command
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            if device_map_revealed:
                device_map_revealed = False
                return CommandResult(0, DEVICE_MAP_UI_XML, "")
            if result_ready == "mac-process":
                return CommandResult(0, MAC_PROCESS_UI_XML, "")
            if result_ready == "phone":
                return CommandResult(0, PHONE_UI_XML, "")
            if submitted_command == "mac-process":
                return CommandResult(0, MAC_PROCESS_COMMAND_TYPED_UI_XML, "")
            if submitted_command == "phone":
                return CommandResult(0, COMMAND_TYPED_UI_XML, "")
            return CommandResult(0, BASE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        mac_command=smoke.DEFAULT_MAC_PROCESS_COMMAND,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert any(
        step.name == "MAC command smoke" and step.status is StepStatus.OK for step in report.steps
    )


def test_include_mac_can_smoke_goffy_rom_status_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)
    monkeypatch.setattr(
        smoke,
        "capture_screenshot",
        lambda **kwargs: DeviceSmokeStep(
            name="Capture screenshot",
            status=StepStatus.OK,
            artifact="final.png",
        ),
    )
    submitted_command: str | None = None
    result_ready: str | None = None
    device_map_revealed = False

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal device_map_revealed, result_ready, submitted_command
        target = target_runner(command)
        if target is not None:
            return target
        if (
            adb_args(command) == ("shell", "input", "swipe", "360", "1450", "360", "900", "350")
            and submitted_command is None
        ):
            device_map_revealed = True
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("shell", "input", "text", "check%smy%sbattery%slevel"):
            submitted_command = "phone"
            result_ready = None
            return CommandResult(0, "ok", "")
        if adb_args(command) == (
            "shell",
            "input",
            "text",
            "Show%sGOFFY%sROM%sstatus",
        ):
            submitted_command = "mac-rom-status"
            result_ready = None
            return CommandResult(0, "ok", "")
        if (
            adb_args(command)[:3] == ("shell", "input", "tap")
            and submitted_command is not None
            and result_ready is None
        ):
            result_ready = submitted_command
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            if device_map_revealed:
                device_map_revealed = False
                return CommandResult(0, DEVICE_MAP_UI_XML, "")
            if result_ready == "mac-rom-status":
                return CommandResult(0, MAC_ROM_STATUS_UI_XML, "")
            if result_ready == "phone":
                return CommandResult(0, PHONE_UI_XML, "")
            if submitted_command == "mac-rom-status":
                return CommandResult(0, MAC_ROM_STATUS_COMMAND_TYPED_UI_XML, "")
            if submitted_command == "phone":
                return CommandResult(0, COMMAND_TYPED_UI_XML, "")
            return CommandResult(0, BASE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        mac_command=smoke.DEFAULT_MAC_ROM_STATUS_COMMAND,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert smoke.mac_tool_for_smoke(smoke.DEFAULT_MAC_ROM_STATUS_COMMAND) == "goffy.rom.status"
    assert any(
        step.name == "MAC command smoke" and step.status is StepStatus.OK for step in report.steps
    )


def test_debug_hub_token_file_must_stay_under_validation_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    token_file = tmp_path.parent / f"{tmp_path.name}-outside-token"
    token_file.write_text("a" * 32, encoding="utf-8")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        debug_hub_token_file=token_file,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert any(
        step.detail == "debug Hub token file must live under .goffy-validation"
        for step in report.steps
    )


def test_debug_hub_token_file_invalid_utf8_returns_bounded_failure(tmp_path: Path) -> None:
    token_file = tmp_path / ".goffy-validation" / "runtime" / "dev-hub-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_bytes(b"\xff\xfe\xfd")

    token, failure = smoke.read_debug_hub_token(tmp_path, token_file)

    assert token == ""
    assert failure is not None
    assert failure.status is StepStatus.FAIL
    assert failure.detail == "debug Hub token file could not be read"


def test_debug_hub_link_rechecks_after_second_bounded_scroll(tmp_path: Path) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    token = "abcdef0123456789abcdef0123456789"  # noqa: S105
    token_file = tmp_path / ".goffy-validation" / "runtime" / "dev-hub-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text(token, encoding="utf-8")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    ui_outputs = iter(
        (
            DEBUG_SETUP_UI_XML,
            DEBUG_TOKEN_FOCUSED_UI_XML,
            DEBUG_SETUP_UI_XML,
            DEBUG_SETUP_UI_XML,
            DEBUG_LINK_BUTTON_UI_XML,
            DEBUG_LINK_CONFIGURED_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            return CommandResult(0, next(ui_outputs), "")
        return CommandResult(0, "ok", "")

    result = smoke.configure_debug_hub_link(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        token_file=token_file,
        output_directory=output_directory,
    )

    assert result.status is StepStatus.OK
    swipes = [
        command
        for command in seen
        if adb_args(command) == ("shell", "input", "swipe", "360", "1500", "360", "900", "500")
    ]
    assert len(swipes) == 2


def test_include_mac_can_configure_debug_hub_link_from_local_token_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    token = "abcdef0123456789abcdef0123456789"  # noqa: S105
    token_file = tmp_path / ".goffy-validation" / "runtime" / "dev-hub-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text(token, encoding="utf-8")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)
    monkeypatch.setattr(
        smoke,
        "capture_screenshot",
        lambda **kwargs: DeviceSmokeStep(
            name="Capture screenshot",
            status=StepStatus.OK,
            artifact="final.png",
        ),
    )
    setup_outputs = iter(
        (
            BASE_UI_XML,
            DEBUG_SETUP_UI_XML,
            DEBUG_TOKEN_FOCUSED_UI_XML,
            DEBUG_LINK_BUTTON_UI_XML,
            DEBUG_LINK_CONFIGURED_UI_XML,
            DEBUG_LINK_CONFIGURED_UI_XML,
            BASE_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []
    submitted_command: str | None = None
    result_ready: str | None = None
    device_map_revealed = False

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal device_map_revealed, result_ready, submitted_command
        seen.append(tuple(command))
        target = target_runner(command)
        if target is not None:
            return target
        if (
            adb_args(command) == ("shell", "input", "swipe", "360", "1450", "360", "900", "350")
            and submitted_command is None
        ):
            device_map_revealed = True
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("shell", "input", "text", "check%smy%sbattery%slevel"):
            submitted_command = "phone"
            result_ready = None
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("shell", "input", "text", "check%smy%sMac%sstatus"):
            submitted_command = "mac"
            result_ready = None
            return CommandResult(0, "ok", "")
        if (
            adb_args(command)[:3] == ("shell", "input", "tap")
            and submitted_command is not None
            and result_ready is None
        ):
            result_ready = submitted_command
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            if device_map_revealed:
                device_map_revealed = False
                return CommandResult(0, DEVICE_MAP_UI_XML, "")
            if result_ready == "mac":
                return CommandResult(0, MAC_UI_XML, "")
            if result_ready == "phone":
                return CommandResult(0, PHONE_UI_XML, "")
            if submitted_command == "mac":
                return CommandResult(0, MAC_COMMAND_TYPED_UI_XML, "")
            if submitted_command == "phone":
                return CommandResult(0, COMMAND_TYPED_UI_XML, "")
            try:
                return CommandResult(0, next(setup_outputs), "")
            except StopIteration:
                return CommandResult(0, BASE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        debug_hub_token_file=token_file,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert any(
        step.name == "Configure debug Hub link" and step.status is StepStatus.OK
        for step in report.steps
    )
    assert any(
        step.name == "MAC command smoke" and step.status is StepStatus.OK for step in report.steps
    )
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "swipe",
        "360",
        "1450",
        "360",
        "650",
        "450",
    ) in seen
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "text",
        token,
    ) in seen
    assert (tmp_path / "artifacts" / "debug-hub-link.xml").is_file()
    assert token not in (tmp_path / "artifacts" / "debug-hub-link.xml").read_text(encoding="utf-8")
    rendered = render_text(report)
    payload = render_json(report)
    assert token not in rendered
    assert token not in payload


def test_debug_token_field_prefers_development_token_input_over_command_input() -> None:
    token_field = smoke.find_debug_token_field(DEBUG_SETUP_WITH_COMMAND_INPUT_UI_XML)

    assert token_field is not None
    assert token_field.bounds == (60, 776, 660, 871)


def test_focused_debug_token_field_requires_focus() -> None:
    assert smoke.find_focused_debug_token_field(DEBUG_SETUP_UI_XML) is None

    focused = smoke.find_focused_debug_token_field(DEBUG_TOKEN_FOCUSED_UI_XML)

    assert focused is not None
    assert focused.bounds == (60, 776, 660, 871)


def test_text_field_entry_area_taps_lower_right_input_region(tmp_path: Path) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    token_field = smoke.find_debug_token_field(DEBUG_SETUP_UI_XML)
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "ok", "")

    assert token_field is not None
    result = smoke.tap_text_field_entry_area(
        adb,
        target,
        tmp_path,
        runner,
        30,
        token_field,
        step_name="Focus token input",
    )

    assert result.status is StepStatus.OK
    assert adb_args(seen[0]) == ("shell", "input", "tap", "612", "851")


def test_debug_link_action_rejects_disabled_compose_button() -> None:
    debug_link = smoke.find_enabled_action_for_text(
        DEBUG_LINK_DISABLED_BUTTON_UI_XML,
        text="Debug link",
    )

    assert debug_link is None


def test_token_in_unmasked_edit_text_detects_wrong_input() -> None:
    token = "abcdef0123456789abcdef0123456789"  # noqa: S105
    wrong_input_xml = DEBUG_SETUP_WITH_COMMAND_INPUT_UI_XML.replace(
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,1449][660,1589]" />',
        f'  <node text="{token}" class="android.widget.EditText" enabled="true" '
        'bounds="[60,1449][660,1589]" />',
        1,
    )

    assert smoke.token_in_unmasked_edit_text(wrong_input_xml, token)


def test_debug_hub_link_artifact_redaction_stays_parseable(tmp_path: Path) -> None:
    token = "abcdef0123456789abcdef0123456789"  # noqa: S105
    ui_xml = DEBUG_SETUP_WITH_COMMAND_INPUT_UI_XML.replace(
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,1449][660,1589]" />',
        f'  <node text="{token}" class="android.widget.EditText" enabled="true" '
        'bounds="[60,1449][660,1589]" />',
        1,
    )

    smoke.write_debug_hub_link_artifact(tmp_path, ui_xml, token)
    redacted = (tmp_path / "debug-hub-link.xml").read_text(encoding="utf-8")

    assert token not in redacted
    assert smoke.DEBUG_HUB_TOKEN_PLACEHOLDER in redacted
    ET.fromstring(redacted)  # noqa: S314


def test_clear_focused_text_field_uses_bounded_keyevents(tmp_path: Path) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "ok", "")

    result = smoke.clear_focused_text_field(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        step_name="Clear input",
    )

    assert result.status is StepStatus.OK
    keyevents = adb_args(seen[0])
    assert keyevents[:4] == ("shell", "input", "keyevent", "KEYCODE_MOVE_END")
    assert keyevents.count("KEYCODE_DEL") == smoke.MAX_INPUT_TEXT_LENGTH


def test_command_window_requires_markers_after_matching_command() -> None:
    assert command_window_contains(
        PHONE_UI_XML,
        "check my battery level",
        ("VERIFIED", "%", "Battery status matched the local tool contract."),
    )
    assert not command_window_contains(
        PHONE_UI_XML,
        "check my battery level",
        ("VERIFIED", "Darwin", "mac.system_info output matched the registered schema."),
    )
    assert not command_window_contains(
        PHONE_UI_XML_FRESH_PENDING_THEN_STALE_SUCCESS,
        "check my battery level",
        ("VERIFIED", "%", "Battery status matched the local tool contract."),
        fresh_count=1,
    )
    assert not command_window_contains(
        MEMORY_LIST_EMPTY_WITH_OLDER_REMEMBER_UI_XML,
        smoke.DEFAULT_MEMORY_LIST_COMMAND,
        ("VERIFIED", "MEMORIES", "phone.memory.list", TEST_MEMORY_TEXT),
        fresh_count=1,
    )
    assert timeline_command_occurrences(PHONE_UI_XML, "check my battery level") == 1


def test_timeline_command_occurrences_ignore_command_input_without_timeline() -> None:
    assert (
        timeline_command_occurrences(
            COMMAND_TYPED_SEND_OFFSCREEN_UI_XML,
            "check my battery level",
        )
        == 0
    )


def test_timeline_command_occurrences_ignore_edit_text_after_timeline() -> None:
    xml = "\n".join(
        [
            "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
            '<hierarchy rotation="0">',
            '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
            'bounds="[60,1200][260,1240]" />',
            '  <node text="check my battery level" class="android.widget.EditText" '
            'enabled="true" bounds="[60,1300][660,1440]" />',
            "</hierarchy>",
        ]
    )

    assert timeline_command_occurrences(xml, "check my battery level") == 0


def test_renderers_redact_paths_and_mark_mutating_steps(tmp_path: Path) -> None:
    report = smoke.DeviceSmokeReport(
        executed=True,
        ok=False,
        output_directory=str(tmp_path / "artifacts"),
        phone_command=str(tmp_path / "phone-command"),
        mac_command=str(tmp_path / "mac-command"),
        steps=(
            DeviceSmokeStep(
                name="Launch GOFFY",
                status=StepStatus.OK,
                command=("/opt/android/adb", "shell", "am", "start", "-n", smoke.MAIN_ACTIVITY),
                mutates_device=True,
                detail=str(tmp_path / "detail"),
                artifact="final.png",
            ),
        ),
        repo_root=tmp_path,
    )

    rendered = render_text(report)
    payload = render_json(report)

    assert str(tmp_path) not in rendered
    assert str(tmp_path) not in payload
    assert "mutates-device: true" in rendered
    assert "final.png" in rendered


def test_main_plan_json_returns_success(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--json"]) == 0

    assert '"schemaVersion": "goffy.moto-g-device-smoke.v1"' in capsys.readouterr().out
