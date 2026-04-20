"""
whatsapp.py
───────────
WhatsApp dispatch via Twilio.
If TWILIO_ACCOUNT_SID is not set in .env, all sends are stubbed
(the work order is still logged, just no SMS is sent).
"""

import os
from dotenv import load_dotenv

load_dotenv()

TWILIO_SID   = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM  = os.getenv('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886')

CREW_PHONES = {
    'Z1': os.getenv('CREW_Z1_PHONE', '+919876543210'),
    'Z2': os.getenv('CREW_Z2_PHONE', '+919876543211'),
    'Z3': os.getenv('CREW_Z3_PHONE', '+919876543212'),
}

NRW_EMOJI = {
    'pipe_burst':   '🔴',
    'slow_seepage': '🟡',
    'illegal_tap':  '🟣',
    'meter_tamper': '🟠',
    'none':         '🟢',
}


def get_crew_phone(zone: str) -> str:
    return CREW_PHONES.get(zone, CREW_PHONES['Z1'])


def build_whatsapp_message(nrw_type, zone, segment_id, urgency,
                            estimated_loss, lat, lon, work_order_id) -> str:
    labels = {
        'pipe_burst':   'Pipe Burst',
        'slow_seepage': 'Slow Seepage',
        'illegal_tap':  'Illegal Tap',
        'meter_tamper': 'Meter Tampering',
        'none':         'Normal',
    }
    emoji = NRW_EMOJI.get(nrw_type, '⚠️')
    label = labels.get(nrw_type, nrw_type)
    maps_url = f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"

    return (
        f"{emoji} *AquaWatch NRW ALERT*\n"
        f"Work Order: `#{work_order_id}`\n\n"
        f"*Type:* {label}\n"
        f"*Zone:* {zone}  |  *Urgency:* {urgency}\n"
        f"*Segment:* {segment_id}\n"
        f"*Est. Loss:* {int(estimated_loss):,} L/hr\n"
        f"*Location:* {maps_url}\n\n"
        f"Reply *DONE {work_order_id}* when resolved."
    )


def send_whatsapp_alert(to_number: str, message: str) -> dict:
    """
    Send a WhatsApp message via Twilio.
    Returns {'success': bool, 'message_sid': str|None, 'error': str|None}
    """
    if not TWILIO_SID or TWILIO_SID.startswith('ACxxx'):
        # Twilio not configured — stub mode
        print(f"[WhatsApp STUB] Would send to {to_number}:\n{message}\n")
        return {'success': True, 'message_sid': 'STUB-' + to_number[-4:], 'error': None}

    try:
        from twilio.rest import Client
        client  = Client(TWILIO_SID, TWILIO_TOKEN)
        to_wa   = f"whatsapp:{to_number}" if not to_number.startswith('whatsapp:') else to_number
        from_wa = TWILIO_FROM if TWILIO_FROM.startswith('whatsapp:') else f"whatsapp:{TWILIO_FROM}"

        msg = client.messages.create(body=message, from_=from_wa, to=to_wa)
        print(f"✅  WhatsApp sent to {to_number}  SID: {msg.sid}")
        return {'success': True, 'message_sid': msg.sid, 'error': None}

    except Exception as e:
        print(f"❌  WhatsApp send failed: {e}")
        return {'success': False, 'message_sid': None, 'error': str(e)}
