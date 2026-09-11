from utils.caldav_client import parse_ics

VEVENT = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:abc-123
DTSTART:20260913T050000Z
DTEND:20260913T053000Z
SUMMARY:Kitchen dishes
{extra}END:VEVENT
END:VCALENDAR"""


def test_parse_ics_defaults_generated_to_false():
    event = parse_ics(VEVENT.format(extra=""))
    assert event["generated"] is False


def test_parse_ics_reads_generated_block_marker():
    event = parse_ics(VEVENT.format(extra="X-GENERATED-BLOCK:TRUE\n"))
    assert event["generated"] is True
