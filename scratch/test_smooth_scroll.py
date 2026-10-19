# c:/Users/Kacper/Desktop/skrypt/scratch/test_smooth_scroll.py
import sys
import os
sys.path.insert(0, os.path.abspath(r"c:\Users\Kacper\Desktop\skrypt\app"))

import tkinter as tk
import customtkinter as ctk
from deal_engine import Offer, AIOfferEvaluator
from gui import DealCard, THEME

app = ctk.CTk()
app.geometry("1100x800")

scroll_feed = ctk.CTkScrollableFrame(
    app,
    fg_color=THEME["bg_feed_scroll"],
    corner_radius=12,
    border_width=1,
    border_color="#221742"
)
scroll_feed.pack(fill="both", expand=True, padx=20, pady=20)

# Create 15 cards
sample_images = [
    "https://images1.vinted.net/t/01_023a7_XfvAxLTwXXwvyXrXpkKuLSpn/f800/89dfcbe8.webp",
    "https://images1.vinted.net/t/05_021c8_7BWQYBfX7W24xouKs3oDu8ge/f800/640dadb0.webp",
]

for i in range(15):
    o = Offer(
        id=f"test_{i}",
        platform="VINTED" if i % 2 == 0 else "OLX",
        title=f"Apple iPhone 16 128GB Pink okazja {i+1}",
        price=1750.0 + i * 20,
        url="https://vinted.pl",
        image_url=sample_images[0],
        created_at_str="Teraz",
        has_delivery=True,
        location_name="Łódź",
        images=sample_images,
        is_deal=(i % 3 == 0)
    )
    o.ai_evaluation = AIOfferEvaluator.evaluate_offer(o)
    card = DealCard(scroll_feed, offer=o, show_image=True, app_cfg={})
    card.pack(fill="x", padx=4, pady=6)

app.update_idletasks()
print("Created 15 cards successfully!")

# Test smooth scroll patch
def install_smooth_scroll(scroll_frame):
    canvas = scroll_frame._parent_canvas

    def _optimized_wheel(event):
        if scroll_frame._check_if_valid_scroll(event.widget):
            if canvas.yview() != (0.0, 1.0):
                # Standard step on Windows is 120
                delta = event.delta
                steps = -int(delta / 60) # Płynniejsze, mniejsze kroki
                if steps == 0:
                    steps = -1 if delta > 0 else 1
                canvas.yview_scroll(steps, "units")
                canvas.update_idletasks()
                return "break"

    scroll_frame.bind_all("<MouseWheel>", _optimized_wheel, add=True)

install_smooth_scroll(scroll_feed)
print("Smooth scroll installed!")
app.destroy()
print("Done!")
