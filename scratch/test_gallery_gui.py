# c:/Users/Kacper/Desktop/skrypt/scratch/test_gallery_gui.py
import sys
import os
sys.path.insert(0, os.path.abspath(r"c:\Users\Kacper\Desktop\skrypt\app"))

import tkinter as tk
import customtkinter as ctk
from deal_engine import Offer, AIOfferEvaluator
from gui import DealCard, CyberLightboxModal, CyberAIModal

ctk.set_appearance_mode("dark")
root = ctk.CTk()
root.geometry("800x600")

sample_images = [
    "https://images1.vinted.net/t/01_023a7_XfvAxLTwXXwvyXrXpkKuLSpn/f800/89dfcbe8.webp",
    "https://images1.vinted.net/t/05_021c8_7BWQYBfX7W24xouKs3oDu8ge/f800/640dadb0.webp",
    "https://images1.vinted.net/t/06_010ea_shXVwWRFpcsAkdALcc6uiTC1/f800/cd9cfceb.webp"
]

offer1 = Offer(
    id="test_1",
    platform="OLX",
    title="iPhone 13 128GB zbita szybka dotyk działa",
    price=750.0,
    url="https://www.olx.pl/d/oferta/test-1",
    image_url=sample_images[0],
    created_at_str="12:30",
    has_delivery=True,
    location_name="Łódź",
    images=sample_images
)
offer1.ai_evaluation = AIOfferEvaluator.evaluate_offer(offer1)

card = DealCard(root, offer=offer1, show_image=True, app_cfg={})
card.pack(fill="x", padx=10, pady=10)

print("DealCard created successfully!")
print("AI verdict:", offer1.ai_evaluation['verdict_badge'])
print("Damage:", offer1.ai_evaluation['damage_name'])
print("Repair total:", offer1.ai_evaluation['repair_total_range'])
print("Profit after repair:", offer1.ai_evaluation['profit_after_repair'], "zł")

root.update_idletasks()
root.destroy()
print("GUI test completed successfully with 0 errors!")
