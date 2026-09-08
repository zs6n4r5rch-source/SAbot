"""Legacy page composer retired in R1-R3 rebuild.

The unified Mini App is now served directly by the single FastAPI route owner.
This compatibility module remains importable for old code paths but performs no
runtime monkey-patching or frontend injection.
"""

def compose_page(html: str) -> str:
    return html

def install(app):
    return app
