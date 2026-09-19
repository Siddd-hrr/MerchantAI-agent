from services.offer_engine.routers.catalog import router as catalog_router
from services.offer_engine.routers.combos import router as combos_router
from services.offer_engine.routers.coupons import router as coupons_router
from services.offer_engine.routers.cross_sell import router as cross_sell_router
from services.offer_engine.routers.discounts import router as discounts_router
from services.offer_engine.routers.festival_campaigns import router as festival_campaigns_router
from services.offer_engine.routers.offers import router as offers_router

__all__ = [
    "discounts_router",
    "combos_router",
    "coupons_router",
    "festival_campaigns_router",
    "cross_sell_router",
    "offers_router",
    "catalog_router",
]
