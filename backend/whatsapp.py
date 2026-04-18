import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────
# TWILIO CONFIG
# Reads from .env file — never hardcode keys
# ─────────────────────────────────────────
TWILIO_SID       = os.getenv('TWILIO_SID')
TWILIO_AUTH      = os.getenv('TWILIO_AUTH')
TWILIO_FROM      = os.getenv('TWILIO_FROM', 'whatsapp:+14155238886')  # Twilio sandbox default
TWILIO_WEBHOOK   = os.getenv('TWILIO_WEBHOOK_URL', '')                # your public URL for confirm

# Zone → crew WhatsApp numbers (set in .env)
CREW_PHONES = {
    'Z1': os.getenv('CREW_PHONE_Z1', ''),
    'Z2': os.getenv('CREW_PHONE_Z2', ''),
    'Z3': os.getenv('CREW_PHONE_Z3', ''),
}


def get_crew_phone(zone: str) -> str:
    """Return the WhatsApp number for the crew assigned to a zone."""
    return CREW_PHONES.get(zone, '')


def build_whatsapp_message(
    nrw_type: str,
    zone: str,
    segment_id: str,
    urgency: str,
    estimated_loss: float,
    lat: float,
    lon: float,
    work_order_id: str
) -> str:
    """
    Build a structured WhatsApp work-order message.
    Field crew needs: what, where, how urgent — nothing else.
    """
    type_labels = {
        'pipe_burst':   '🔴 PIPE BURST',
        'slow_seepage': '🟡 SLOW SEEPAGE',
        'illegal_tap':  '🟣 ILLEGAL TAP',
        'meter_tamper': '🟠 METER TAMPERING',
        'none':         '🟢 NORMAL',
    }
    urgency_emoji = {'HIGH': '🚨', 'MEDIUM': '⚠️', 'LOW': 'ℹ️'}

    label        = type_labels.get(nrw_type, nrw_type.upper())
    urg_icon     = urgency_emoji.get(urgency, '')
    maps_link    = f"https://maps.google.com/?q={lat},{lon}"
    loss_display = f"{int(estimated_loss):,}"

    message = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💧 *NRW WORK ORDER #{work_order_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*Type:*    {label}\n"
        f"*Zone:*    {zone}  |  *Segment:* {segment_id}\n"
        f"*Urgency:* {urg_icon} {urgency}\n"
        f"*Est. Loss:* {loss_display} litres/hr\n"
        f"\n"
        f"📍 *Location:*\n"
        f"{maps_link}\n"
        f"\n"
        f"✅ Reply *DONE {work_order_id}* when resolved.\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    return message


def send_whatsapp_alert(to_number: str, message: str) -> dict:
    """
    Send a WhatsApp message via Twilio.

    Returns a dict with:
        success (bool)
        message_sid (str | None)
        error (str | None)
    """
    if not TWILIO_SID or not TWILIO_AUTH:
        return {
            'success': False,
            'message_sid': None,
            'error': 'Twilio credentials not configured. Check TWILIO_SID and TWILIO_AUTH in .env'
        }

    if not to_number:
        return {
            'success': False,
            'message_sid': None,
            'error': 'No crew phone number configured for this zone.'
        }

    try:
        client = Client(TWILIO_SID, TWILIO_AUTH)
        msg = client.messages.create(
            from_=TWILIO_FROM,
            body=message,
            to=f'whatsapp:{to_number}'
        )
        return {
            'success': True,
            'message_sid': msg.sid,
            'error': None
        }
    except Exception as e:
        return {
            'success': False,
            'message_sid': None,
            'error': str(e)
        }
