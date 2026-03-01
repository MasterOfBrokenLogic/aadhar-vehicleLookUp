#!/usr/bin/env python3
"""
OSINT Terminal Bot — Built by @drazeforce
"""

import asyncio
import logging
import os
import re
from dotenv import load_dotenv
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()

# ── CONFIG ─────────────────────────────────────────────────────────────────────
BOT_TOKEN        = os.getenv("BOT_TOKEN")
AADHAR_API_BASE  = os.getenv("AADHAR_API_BASE", "https://aadhar-to-family-demo.vercel.app/")
AADHAR_API_KEY   = os.getenv("AADHAR_API_KEY",  "DEMOOOOOO")
VEHICLE_API_BASE = os.getenv("VEHICLE_API_BASE", "https://car-mix-fee-demo.vercel.app/")
VEHICLE_API_KEY  = os.getenv("VEHICLE_API_KEY",  "DEMO")

AWAITING_AADHAR  = "awaiting_aadhar"
AWAITING_VEHICLE = "awaiting_vehicle"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── KEYBOARDS ──────────────────────────────────────────────────────────────────

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Aadhar to Family Info", callback_data="aadhar_info")],
        [InlineKeyboardButton("Vehicle Info",          callback_data="vehicle_info")],
        [InlineKeyboardButton("Help",                  callback_data="help")],
    ])

def back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Back to Menu", callback_data="main_menu")],
    ])


# ── LOADER ─────────────────────────────────────────────────────────────────────

LOADER_STEPS = [
    "Initializing secure session",
    "Establishing encrypted tunnel",
    "Authenticating access credentials",
    "Reaching primary node",
    "Querying API endpoints",
    "Aggregating cross-source data",
    "Resolving field conflicts",
    "Compiling intelligence report",
]

async def run_loader(msg, stop_event: asyncio.Event):
    idx = 0
    tick = 0
    while not stop_event.is_set():
        step  = LOADER_STEPS[idx % len(LOADER_STEPS)]
        trail = "·" * (tick % 4)
        try:
            await msg.edit_text(
                f"<code>[ PROCESSING ]</code>\n\n<i>{step}{trail}</i>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        tick += 1
        if tick % 4 == 0:
            idx += 1
        await asyncio.sleep(0.75)


# ── VALIDATION ─────────────────────────────────────────────────────────────────

def validate_aadhar(raw: str):
    cleaned = raw.replace(" ", "").replace("-", "")
    if not cleaned.isdigit():
        return None, "Only numeric digits are accepted."
    if len(cleaned) != 12:
        return None, f"Expected 12 digits — received {len(cleaned)}."
    if cleaned[0] in ("0", "1"):
        return None, "Aadhar numbers cannot begin with 0 or 1."
    if len(set(cleaned)) == 1:
        return None, "This number appears to be invalid."
    return cleaned, None

def validate_rc(raw: str):
    cleaned = raw.replace(" ", "").upper()
    if not re.match(r"^[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}$", cleaned):
        return None, "Invalid RC format. Expected format: KL41V2354 or MH12AB1234"
    return cleaned, None


# ── SHARED UTILS ───────────────────────────────────────────────────────────────

DIV  = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
THIN = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

_NULL = {None, "", "N/A", "NA", "null", "None", "n/a", "na", "0", "undefined", "-"}

def _v(*sources) -> str:
    for s in sources:
        val = str(s).strip() if s is not None else ""
        if val and val not in _NULL:
            return val
    return ""

def f(label: str, *values, indent: int = 2) -> str:
    v = _v(*values)
    display = v if v else "—"
    pad = " " * indent
    return f"{pad}<b>{label}</b>  <code>{display}</code>\n"

def _merge_chunks(pages: list, limit: int = 4000) -> list[str]:
    chunks, current = [], ""
    for page in pages:
        if len(current) + len(page) > limit:
            if current:
                chunks.append(current)
            current = page
        else:
            current += page
    if current.strip():
        chunks.append(current)
    return chunks


# ══════════════════════════════════════════════════════════════════════════════
#  AADHAR MODULE
# ══════════════════════════════════════════════════════════════════════════════

def _aadhar_merge_list_records(full: dict) -> list:
    all_records = []
    for key in [f"api_{i}" for i in range(1, 7)]:
        result = full.get(key, {}).get("result", [])
        if isinstance(result, list):
            all_records.extend(result)

    merged = {}
    for r in all_records:
        dk = (r.get("name","").strip().lower(), r.get("mobile","").strip())
        if dk not in merged:
            merged[dk] = dict(r)
            merged[dk]["extra_alts"]      = set()
            merged[dk]["extra_addresses"] = set()
        else:
            ex = merged[dk]
            for fld in ["fname","id","mobile","alt","email","address","name"]:
                if not _v(ex.get(fld)) and _v(r.get(fld)):
                    ex[fld] = r[fld]
            if _v(r.get("alt")) and r["alt"] != ex.get("mobile") and r["alt"] != ex.get("alt"):
                ex["extra_alts"].add(r["alt"])
            if _v(r.get("address")) and r["address"] != ex.get("address"):
                ex["extra_addresses"].add(r["address"])
    return list(merged.values())

def _aadhar_get_impds(full: dict) -> dict | None:
    for key in [f"api_{i}" for i in range(1, 7)]:
        result = full.get(key, {}).get("result", {})
        if (
            isinstance(result, dict)
            and result.get("rs") == "S"
            and result.get("rd") == "Success"
            and result.get("pd")
        ):
            return result
    return None

def _aadhar_node_statuses(full: dict) -> str:
    icons = {"ok_list":"ONLINE","ok_dict":"ONLINE","empty":"EMPTY",
             "no_records":"NO DATA","failed":"FAILED","not_present":"ABSENT"}
    parts = []
    for key in [f"api_{i}" for i in range(1, 7)]:
        api = full.get(key, {})
        if not api:
            s = "not_present"
        elif not api.get("success", False):
            s = "failed"
        else:
            result = api.get("result", None)
            if isinstance(result, list) and result:
                s = "ok_list"
            elif isinstance(result, dict) and result.get("rs") == "S":
                s = "ok_dict"
            elif isinstance(result, dict) and result.get("error"):
                s = "no_records"
            else:
                s = "empty"
        parts.append(f"<code>{key.upper().replace('_',' ')}: {icons[s]}</code>")
    return "  ".join(parts)

def build_aadhar_report(full: dict, aadhar: str) -> list[str]:
    pages    = []
    records  = _aadhar_merge_list_records(full)
    impds    = _aadhar_get_impds(full)
    statuses = _aadhar_node_statuses(full)

    # Header
    pages.append(
        f"<code>{DIV}</code>\n"
        f"<b>AADHAR INTELLIGENCE REPORT</b>\n"
        f"<code>{DIV}</code>\n\n"
        f"<b>Query</b>    <code>{aadhar}</code>\n"
        f"<b>Nodes</b>    {statuses}\n"
        f"<b>Records</b>  <code>{len(records)} identity match(es)</code>\n"
    )

    # Identity records
    for i, r in enumerate(records, 1):
        block  = f"\n<code>{THIN}</code>\n<b>RECORD {i} of {len(records)}</b>\n<code>{THIN}</code>\n\n"
        block += "<b>Identity</b>\n"
        block += f("Name",         r.get("name",""))
        block += f("Father/Guard", r.get("fname",""))
        block += f("Aadhar ID",    r.get("id",""))
        block += "\n<b>Contact</b>\n"
        block += f("Primary",   r.get("mobile",""))
        block += f("Alternate", r.get("alt",""))
        for ea in r.get("extra_alts", set()):
            block += f("Alt (other)", ea)
        block += f("Email", r.get("email",""))
        block += "\n<b>Address</b>\n"
        block += f"  <code>{_v(r.get('address','')) or '—'}</code>\n"
        for ea in r.get("extra_addresses", set()):
            block += f"\n  <b>Alt Address</b>\n  <code>{ea}</code>\n"
        pages.append(block)

    # IMPDS / Ration Card
    if impds:
        pd  = impds.get("pd", {})
        ph  = impds.get("purchase_history", {}).get("pd", [])

        rc  = (
            f"\n<code>{THIN}</code>\n<b>RATION CARD  /  IMPDS</b>\n<code>{THIN}</code>\n\n"
            + f("Source",        impds.get("source",""))
            + f("Linked Aadhar", impds.get("source_impds_aadhaar",""))
            + f("Card ID",       pd.get("rcId",""))
            + f("Scheme",        f"{pd.get('schemeName','')}  ({pd.get('schemeId','')})")
            + f("FPS ID",        pd.get("fpsId",""))
            + f("State",         f"{pd.get('homeStateName','')}  (Code: {pd.get('homeStateCode','')})")
            + f("District",      f"{pd.get('homeDistName','')}  (Code: {pd.get('districtCode','')})")
            + f("ONORC Allowed", pd.get("allowed_onorc",""))
            + f("Duplicate UID", pd.get("dup_uid_status",""))
            + f"\n<b>Registered Address</b>\n  <code>{_v(pd.get('address','')) or '—'}</code>\n"
        )
        pages.append(rc)

        members = pd.get("memberDetailsList", [])
        if members:
            fam = f"\n<code>{THIN}</code>\n<b>FAMILY MEMBERS  —  {len(members)} member(s)</b>\n<code>{THIN}</code>\n\n"
            for m in members:
                uid_tag = "UID Linked" if m.get("uid") == "Yes" else "No UID"
                fam += (
                    f"  <b>{_v(m.get('memberName','')) or '—'}</b>"
                    f"  <i>({_v(m.get('releationship_name',''))})</i>\n"
                    f"  <code>Member ID     {_v(m.get('memberId',''))}</code>\n"
                    f"  <code>Rel. Code     {_v(m.get('relationship_code',''))}</code>\n"
                    f"  <code>UID Status    {uid_tag}</code>\n\n"
                )
            pages.append(fam)

        if ph:
            hist = f"\n<code>{THIN}</code>\n<b>PURCHASE HISTORY  —  {len(ph)} transaction(s)</b>\n<code>{THIN}</code>\n\n"
            for tx in ph:
                hist += f"  <b>{_v(tx.get('transaction_date','')) or '—'}</b>\n"
                hist += f("Scheme",      tx.get("scheme_name",""))
                hist += f("Member",      tx.get("member_name",""))
                hist += f("Ration Card", tx.get("ration_card_no",""))
                hist += f("Rice",        f"{tx.get('rice',0)} kg")
                hist += f("Wheat",       f"{tx.get('wheat',0)} kg")
                hist += f("CG",          tx.get("cg",""))
                hist += f("Home FPS",    tx.get("home_fps_id",""))
                hist += f("Sale FPS",    tx.get("sale_fps_id",""))
                hist += f("Home State",  f"{tx.get('home_state_name','')} ({tx.get('home_state_short_name','')})")
                hist += f("Sale State",  f"{tx.get('sale_state_name','')} ({tx.get('sale_state_short_namee','')})")
                hist += f("Receipt ID",  tx.get("receipt_id",""))
                hist += f("Recorded On", tx.get("updated_on",""))
                hist += "\n"
            pages.append(hist)

    pages.append(f"\n<code>{DIV}</code>\n<i>Built by @drazeforce</i>")
    return _merge_chunks(pages)


# ══════════════════════════════════════════════════════════════════════════════
#  VEHICLE MODULE
# ══════════════════════════════════════════════════════════════════════════════

def _veh_node_statuses(data_nodes: dict) -> str:
    parts = []
    for key in [f"Api {i}" for i in range(1, 7)]:
        node = data_nodes.get(key, {})
        if not node:
            label = "ABSENT"
        else:
            st = str(node.get("status","")).lower()
            if st in ("success","true","1"):
                label = "ONLINE"
            elif st == "offline":
                label = "OFFLINE"
            elif st == "error":
                label = "ERROR"
            else:
                # Api 3 uses nested data
                if node.get("data") or node.get("vehicle_details"):
                    label = "ONLINE"
                else:
                    label = "EMPTY"
        parts.append(f"<code>{key.upper()}: {label}</code>")
    return "  ".join(parts)


def _veh_get(data_nodes: dict, *keys) -> str:
    """
    Try each key across Api 1 vehicle_details, Api 2 flat dict,
    Api 3 nested data[0], Api 4 vehicle_info.data, in order.
    Returns first non-empty value found.
    """
    sources = []

    api1_vd = data_nodes.get("Api 1", {}).get("vehicle_details", {}) or {}
    api2    = data_nodes.get("Api 2", {}) or {}
    api3_d  = {}
    _api3   = data_nodes.get("Api 3", {})
    if _api3 and isinstance(_api3.get("data"), dict):
        _list = _api3["data"].get("data", [])
        if _list:
            api3_d = _list[0]
    api4_vd = data_nodes.get("Api 4", {}).get("vehicle_info", {}).get("data", {}) or {}

    for key in keys:
        # Normalize key for each API's naming conventions
        camel = key
        val = _v(
            api1_vd.get(key),
            api2.get(key),
            api2.get(camel),
            api3_d.get(key),
            api4_vd.get(key),
        )
        if val:
            return val
    return ""


def build_vehicle_report(raw: dict) -> list[str]:
    pages       = []
    data_nodes  = raw.get("data_nodes", {})
    rc_number   = raw.get("vehicle_identity", "")
    statuses    = _veh_node_statuses(data_nodes)

    # Shortcuts to each API source
    api1        = data_nodes.get("Api 1", {})
    api1_vd     = api1.get("vehicle_details", {}) or {}
    api2        = data_nodes.get("Api 2", {}) or {}
    api3_data   = {}
    _api3       = data_nodes.get("Api 3", {})
    if isinstance(_api3.get("data"), dict):
        _list = _api3["data"].get("data", [])
        if _list:
            api3_data = _list[0]
    api4_vd     = data_nodes.get("Api 4", {}).get("vehicle_info", {}).get("data", {}) or {}
    api4_chal   = data_nodes.get("Api 4", {}).get("challan_info", {}) or {}
    extracted   = raw.get("extracted_owner_details", {})

    # ── Header ────────────────────────────────────────────────────────────────
    pages.append(
        f"<code>{DIV}</code>\n"
        f"<b>VEHICLE INTELLIGENCE REPORT</b>\n"
        f"<code>{DIV}</code>\n\n"
        f"<b>Query</b>    <code>{rc_number}</code>\n"
        f"<b>Nodes</b>    {statuses}\n"
        f"<b>Timestamp</b>  <code>{_v(raw.get('timestamp',''))}</code>\n"
    )

    # ── Registration ──────────────────────────────────────────────────────────
    reg = f"\n<code>{THIN}</code>\n<b>REGISTRATION</b>\n<code>{THIN}</code>\n\n"
    reg += f("RC Number",    api1_vd.get("registration_no"), api3_data.get("reg_no"), api4_vd.get("reg_no"), rc_number)
    reg += f("Status",       api3_data.get("status"), api4_vd.get("status"))
    reg += f("Vehicle Age",  api4_vd.get("vehicle_age"), api3_data.get("vehicle_age"))
    reg += f("Reg. Date",    api1_vd.get("registration_date"), api2.get("Registration Date"), api3_data.get("regn_dt"), api4_vd.get("regn_dt"))
    reg += f("RTO",          api1_vd.get("rto"), api2.get("Registered RTO"), api3_data.get("rto"), api4_vd.get("rto"))
    reg += f("RTO Code",     api4_vd.get("rto_code"))
    pages.append(reg)

    # ── Owner ─────────────────────────────────────────────────────────────────
    own = f"\n<code>{THIN}</code>\n<b>OWNER</b>\n<code>{THIN}</code>\n\n"
    own += f("Name",          api1_vd.get("owner_name"), api2.get("Owner Name"), api3_data.get("owner_name"), api4_vd.get("owner_name"))
    own += f("Father Name",   api1_vd.get("father_name"), api2.get("Father's Name"), api3_data.get("father_name"), api4_vd.get("father_name"))
    own += f("Owner Serial",  api2.get("Owner Serial No"), api4_vd.get("owner_sr_no"), api3_data.get("owner_sr_no"))
    own += f("Address",       api2.get("Address"), api3_data.get("address"))
    own += f("City",          api2.get("City Name"))

    # Phones — combine from all sources
    phones = set()
    for src in [
        api1_vd.get("mobile"),
        api2.get("Phone"),
        api3_data.get("mobile_no"),
    ]:
        if _v(src):
            phones.add(_v(src))
    for ph in extracted.get("phone_nodes", []):
        if _v(ph):
            phones.add(_v(ph))
    for i, ph in enumerate(sorted(phones), 1):
        own += f(f"Phone {i}", ph)
    pages.append(own)

    # ── Vehicle Details ───────────────────────────────────────────────────────
    veh = f"\n<code>{THIN}</code>\n<b>VEHICLE DETAILS</b>\n<code>{THIN}</code>\n\n"
    veh += f("Make / Model",    api1_vd.get("maker_model"), api2.get("Maker Model"), api3_data.get("maker_modal"), api4_vd.get("maker_modal"))
    veh += f("Model Name",      api2.get("Model Name"), api3_data.get("vehicle_model"), api4_vd.get("vehicle_model"))
    veh += f("Vehicle Class",   api2.get("Vehicle Class"), api3_data.get("vh_class"), api4_vd.get("vh_class"))
    veh += f("Vehicle Category",api3_data.get("vehicle_category"), api4_vd.get("vehicle_type"))
    veh += f("Fuel Type",       api1_vd.get("fuel_type"), api2.get("Fuel Type"), api3_data.get("fuel_type"), api4_vd.get("fuel_type"))
    veh += f("Fuel Norms",      api2.get("Fuel Norms"), api3_data.get("fuel_norms"), api4_vd.get("fuel_norms"))
    veh += f("Body Type",       api3_data.get("body_type_desc"), api4_vd.get("body_type"))
    veh += f("Color",           api3_data.get("vehicle_color"), api4_vd.get("vehicle_color"))
    veh += f("Cubic Capacity",  api3_data.get("cubic_cap"), api4_vd.get("cubic_cap"))
    veh += f("No. of Cylinders",api3_data.get("no_of_cyl"), api4_vd.get("no_of_cyl"))
    veh += f("No. of Seats",    api3_data.get("no_of_seats"), api4_vd.get("number_of_seat"))
    veh += f("Engine No.",      api1_vd.get("engine_no"), api3_data.get("engine_no"), api4_vd.get("model_engine"))
    veh += f("Chassis No.",     api1_vd.get("chassis_no"), api3_data.get("chasi_no"), api4_vd.get("chasi_no"))
    veh += f("Wheelbase",       api3_data.get("wheelbase"), api4_vd.get("model_id"))
    veh += f("Unloaded Weight", api3_data.get("rc_unld_wt"), api4_vd.get("unld_wt"))
    veh += f("Resale Value",    api3_data.get("resale_value"))
    pages.append(veh)

    # ── Validity & Compliance ─────────────────────────────────────────────────
    val = f"\n<code>{THIN}</code>\n<b>VALIDITY  &  COMPLIANCE</b>\n<code>{THIN}</code>\n\n"
    val += f("Fitness Upto",     api1_vd.get("fitness_upto"), api2.get("Fitness Upto"), api3_data.get("fitness_upto"), api4_vd.get("fitness_upto"))
    val += f("Tax Upto",         api2.get("Tax Upto"), api3_data.get("tax_upto"), api4_vd.get("tax_upto"))
    val += f("PUC Upto",         api1_vd.get("puc_upto"), api2.get("PUC Upto"), api3_data.get("puc_upto"), api4_vd.get("puc_upto"))
    val += f("PUC No.",          api2.get("PUC No"), api3_data.get("puc_no"), api4_vd.get("puc_no"))
    val += f("PUC Status",       api4_vd.get("puc_expiry_in"))
    val += f("NOC Details",      api3_data.get("noc_details"), api4_vd.get("noc_details"))
    val += f("NP No.",           api3_data.get("rc_np_no"), api4_vd.get("np_no"))
    val += f("NP Issued By",     api3_data.get("rc_np_issued_by"), api4_vd.get("np_issued_by"))
    val += f("NP Valid Upto",    api3_data.get("rc_np_upto"), api4_vd.get("np_upto"))
    pages.append(val)

    # ── Insurance ─────────────────────────────────────────────────────────────
    ins = f"\n<code>{THIN}</code>\n<b>INSURANCE</b>\n<code>{THIN}</code>\n\n"
    ins += f("Company",      api1_vd.get("insurance",{}).get("company"), api2.get("Insurance Company"), api3_data.get("insurance_comp"), api4_vd.get("insurance_company"))
    ins += f("Expiry",       api1_vd.get("insurance",{}).get("expiry"), api2.get("Insurance Expiry"), api3_data.get("insUpto"), api4_vd.get("insurance_upto"))
    ins += f("Expires In",   api4_vd.get("insurance_expiry_in"))
    ins += f("Policy No.",   api2.get("Insurance No"), api3_data.get("ins_policy_no"), api4_vd.get("insurance_no"))
    pages.append(ins)

    # ── Financer ──────────────────────────────────────────────────────────────
    fin = f"\n<code>{THIN}</code>\n<b>FINANCER</b>\n<code>{THIN}</code>\n\n"
    fin += f("Financer",       api1_vd.get("financer"), api2.get("Financier Name"), api3_data.get("financer_details"), api4_vd.get("financer_name"))
    fin += f("Financed From",  api4_vd.get("financed_from"))
    fin += f("Is Commercial",  api3_data.get("is_commercial"))
    pages.append(fin)

    # ── Permit ────────────────────────────────────────────────────────────────
    per = f"\n<code>{THIN}</code>\n<b>PERMIT</b>\n<code>{THIN}</code>\n\n"
    per += f("Permit No.",        api3_data.get("permit_no"), api4_vd.get("permit_no"))
    per += f("Permit Type",       api3_data.get("permit_type"), api4_vd.get("permit_type"))
    per += f("Permit From",       api3_data.get("permit_from"), api4_vd.get("permit_valid_from"))
    per += f("Permit Issued",     api3_data.get("permit_issue_date"), api4_vd.get("permit_issued_dt"))
    per += f("Permit Upto",       api3_data.get("permit_upto"), api4_vd.get("permit_valid_upto"))
    per += f("Sleeper Capacity",  api3_data.get("sleeper_cap"), api4_vd.get("sleeping_cap"))
    per += f("Standing Capacity", api3_data.get("stand_cap"))
    pages.append(per)

    # ── Blacklist ─────────────────────────────────────────────────────────────
    bl = f"\n<code>{THIN}</code>\n<b>BLACKLIST</b>\n<code>{THIN}</code>\n\n"
    bl += f("Status",  api3_data.get("blacklist_status"), api4_vd.get("blacklist_details"))
    bl += f("Details", api3_data.get("blacklist_details"))
    pages.append(bl)

    # ── Challan ───────────────────────────────────────────────────────────────
    if api4_chal:
        rc_chal = api4_chal.get("rc_info","")
        chal_data = api4_chal.get("data","")
        if _v(rc_chal) or _v(chal_data):
            ch = f"\n<code>{THIN}</code>\n<b>CHALLAN INFO</b>\n<code>{THIN}</code>\n\n"
            ch += f("RC Info",  rc_chal)
            ch += f("Data",     chal_data)
            pages.append(ch)

    # ── Source metadata ───────────────────────────────────────────────────────
    meta = f"\n<code>{THIN}</code>\n<b>METADATA</b>\n<code>{THIN}</code>\n\n"
    meta += f("Source (Api 3)", api3_data.get("source"))
    meta += f("Response Type",  api3_data.get("response_type"))
    meta += f("Internal ID",    api3_data.get("id"))
    meta += f("Created At",     api3_data.get("created_at"))
    meta += f("Updated At",     api3_data.get("updated_at"))
    pages.append(meta)

    pages.append(f"\n<code>{DIV}</code>\n<i>Built by @drazeforce</i>")
    return _merge_chunks(pages)


# ── MENU ───────────────────────────────────────────────────────────────────────

async def send_menu(target, edit=False):
    text = (
        "<b>OSINT Terminal</b>\n\n"
        "Operated by <a href='https://t.me/drazeforce'>@drazeforce</a>\n\n"
        "Select a module to continue."
    )
    if edit:
        await target.edit_message_text(
            text, reply_markup=main_menu_kb(),
            parse_mode="HTML", disable_web_page_preview=True
        )
    else:
        await target.reply_text(
            text, reply_markup=main_menu_kb(),
            parse_mode="HTML", disable_web_page_preview=True
        )


# ── HANDLERS ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await send_menu(update.message)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "main_menu":
        context.user_data.clear()
        await send_menu(q, edit=True)

    elif q.data == "aadhar_info":
        context.user_data["state"] = AWAITING_AADHAR
        await q.edit_message_text(
            "<b>Aadhar to Family Info</b>\n\n"
            "Enter a valid 12-digit Aadhar number.\n\n"
            "<i>Formats accepted:  123456789012   or   1234 5678 9012</i>",
            reply_markup=back_kb(),
            parse_mode="HTML"
        )

    elif q.data == "vehicle_info":
        context.user_data["state"] = AWAITING_VEHICLE
        await q.edit_message_text(
            "<b>Vehicle Info</b>\n\n"
            "Enter a valid RC number to begin.\n\n"
            "<i>Examples:  KL41V2354   or   MH12AB1234</i>",
            reply_markup=back_kb(),
            parse_mode="HTML"
        )

    elif q.data == "help":
        await q.edit_message_text(
            "<b>Help</b>\n\n"
            "<b>Aadhar to Family Info</b>\n"
            "Query any 12-digit Aadhar number. Hits all API nodes (1–6), "
            "merges every field and outputs identity, contact, address, "
            "ration card, family tree, and purchase history.\n\n"
            "<b>Vehicle Info</b>\n"
            "Query any RC number. Hits all API nodes (1–6), merges every "
            "field and outputs registration, owner, vehicle specs, insurance, "
            "fitness, PUC, tax, financer, permit, blacklist, and challan data.\n\n"
            "<i>Built by @drazeforce</i>",
            reply_markup=back_kb(),
            parse_mode="HTML"
        )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")

    if state == AWAITING_AADHAR:
        await _handle_aadhar(update, context)
    elif state == AWAITING_VEHICLE:
        await _handle_vehicle(update, context)
    else:
        await send_menu(update.message)


async def _handle_aadhar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aadhar, err = validate_aadhar(update.message.text.strip())
    if err:
        await update.message.reply_text(
            f"<b>Invalid Input</b>\n\n{err}\n\nPlease try again.",
            reply_markup=back_kb(), parse_mode="HTML"
        )
        return

    loader_msg, stop_event, loader_task = await _start_loader(update)

    url = f"{AADHAR_API_BASE}?key={AADHAR_API_KEY}&id={aadhar}"
    chunks, fetch_err = None, None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    fetch_err = f"Remote server returned HTTP {resp.status}."
                else:
                    raw  = await resp.json(content_type=None)
                    full = raw.get("full_details", {})
                    if not full:
                        fetch_err = "API returned an empty payload."
                    else:
                        chunks = build_aadhar_report(full, aadhar)
    except asyncio.TimeoutError:
        fetch_err = "Request timed out. Access point unreachable."
    except Exception as e:
        fetch_err = f"Unexpected error: {e}"

    await _stop_loader(stop_event, loader_task)
    await _deliver(update, loader_msg, chunks, fetch_err)
    context.user_data["state"] = None


async def _handle_vehicle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rc, err = validate_rc(update.message.text.strip())
    if err:
        await update.message.reply_text(
            f"<b>Invalid Input</b>\n\n{err}\n\nPlease try again.",
            reply_markup=back_kb(), parse_mode="HTML"
        )
        return

    loader_msg, stop_event, loader_task = await _start_loader(update)

    url = f"{VEHICLE_API_BASE}?rc={rc}&key={VEHICLE_API_KEY}"
    chunks, fetch_err = None, None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    fetch_err = f"Remote server returned HTTP {resp.status}."
                else:
                    raw = await resp.json(content_type=None)
                    if raw.get("status") not in ("success", "Success", True, "true"):
                        fetch_err = f"API returned status: {raw.get('status','unknown')}."
                    else:
                        chunks = build_vehicle_report(raw)
    except asyncio.TimeoutError:
        fetch_err = "Request timed out. Access point unreachable."
    except Exception as e:
        fetch_err = f"Unexpected error: {e}"

    await _stop_loader(stop_event, loader_task)
    await _deliver(update, loader_msg, chunks, fetch_err)
    context.user_data["state"] = None


# ── SHARED FETCH HELPERS ────────────────────────────────────────────────────────

async def _start_loader(update):
    msg = await update.message.reply_text(
        "<code>[ PROCESSING ]</code>\n\n<i>Initializing secure session</i>",
        parse_mode="HTML"
    )
    stop = asyncio.Event()
    task = asyncio.create_task(run_loader(msg, stop))
    return msg, stop, task

async def _stop_loader(stop_event, task):
    stop_event.set()
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

async def _deliver(update, loader_msg, chunks, fetch_err):
    if fetch_err or not chunks:
        await loader_msg.edit_text(
            f"<code>[ ACCESS DENIED ]</code>\n\n<i>{fetch_err or 'No data returned.'}</i>",
            reply_markup=back_kb(), parse_mode="HTML"
        )
        return
    if len(chunks) == 1:
        await loader_msg.edit_text(chunks[0], reply_markup=back_kb(), parse_mode="HTML")
    else:
        await loader_msg.edit_text(chunks[0], parse_mode="HTML")
        for chunk in chunks[1:-1]:
            await update.message.reply_text(chunk, parse_mode="HTML")
        await update.message.reply_text(chunks[-1], reply_markup=back_kb(), parse_mode="HTML")


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set in .env")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("Bot is online.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()