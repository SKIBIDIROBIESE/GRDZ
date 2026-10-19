# c:/Users/Kacper/Desktop/skrypt/scratch/test_modals.py
import sys
import os
sys.path.insert(0, os.path.abspath(r"c:\Users\Kacper\Desktop\skrypt\app"))

import customtkinter as ctk
from deal_engine import Offer, AIOfferEvaluator
from gui import CyberLightboxModal, CyberAIModal

ctk.set_appearance_mode("dark")
root = ctk.CTk()
root.geometry("400x300")

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

# Test lightbox
lightbox = CyberLightboxModal(root, offer1, initial_index=1)
root.update_idletasks()
lightbox.next_image()
lightbox.prev_image()
lightbox.modal.destroy()
print("Lightbox modal test passed!")

# Test AI modal
ai_modal = CyberAIModal(root, offer1)
root.update_idletasks()
ai_modal.modal.destroy()
print("AI modal test passed!")

root.destroy()
print("All modal tests passed cleanly!")
