"""What needs a person now, for when nobody has the console open.

The daily job's last task fails while this list is not empty, so the job's failure email (to the deploying user) is
the notification; it turns green once each item is handled: a high alert acknowledged, a held feed file released.
The local console in mirror mode also shows desktop notifications for the same events.
"""

from __future__ import annotations


def open_items() -> list[str]:
    from lau.console.services import ops
    from lau.feedback import feed

    items = [
        f"High alert: {a['title']} (raised {a['ts']}; acknowledge it in the console's Alerts screen or "
        f"`lau ack-alert {a['id']} --note ...`)"
        for a in ops.alerts()
        if a["current"] and not a["acknowledged"] and a["severity"] == "high"
    ]
    items += [
        f"Feed file held for review: {f} (review its quarantine, then `lau feed release {f}`)"
        for f in feed.held_files()
    ]
    return items


def check() -> None:
    items = open_items()
    if items:
        raise SystemExit("Needs a person:\n- " + "\n- ".join(items))
    print("nothing needs a person")
