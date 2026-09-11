import os
from elevenlabs import Gemini31FlashLiteImageRequest
from elevenlabs.client import ElevenLabs

# Read API key directly from api_key.txt
with open("api_key.txt", "r") as f:
    api_key = f.read().strip()

# Prompt user for image description
prompt_input = input("Enter image description: ")

client = ElevenLabs(api_key=api_key)

# Generate image using 9:16 aspect ratio
generation = client.flows.image.create(
    request=Gemini31FlashLiteImageRequest(
        model_id="gemini-3.1-flash-lite-image",
        prompt=prompt_input,
        aspect_ratio="9:16",
    )
)

print(f"Generation ID: {generation.id}, Status: {generation.status}")

# Save image file directly
if hasattr(generation, "image_bytes") and generation.image_bytes:
    with open("output.png", "wb") as f:
        f.write(generation.image_bytes)
    print("Image saved as output.png!")

# Display credit cost if returned by SDK
cost = getattr(generation, "cost_in_credits", getattr(generation, "credits_used", "N/A"))
print(f"Price: {cost} credits")
