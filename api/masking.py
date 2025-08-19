
def mask_destination(method: str, raw: str) -> str:
    s = (raw or "").strip()
    m = (method or "").upper()

    # KARTA: 16 raqam -> 8600 **** **** 1234
    if m == "CARD" and s.isdigit() and len(s) == 16:
        return f"{s[:4]} **** **** {s[-4:]}"

    # TELEFON: +99890xxxxxxx -> +99890****567 (PHONE method yo'q bo'lsa ham OTHER bilan kelishi mumkin)
    if s.startswith("+") and len(s) >= 10:
        return f"{s[:6]}****{s[-3:]}"
    if s.isdigit() and len(s) >= 9:
        return f"{s[:4]}****{s[-3:]}"

    # Fallback: o'rtasini yoping
    if len(s) > 6:
        return f"{s[:3]}****{s[-3:]}"
    return s[:1] + "***"
