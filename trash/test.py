# To run this code you need to install the following dependencies:
# pip install google-genai

import base64
import os
from google import genai
from google.genai import types


def generate():
    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
    )

    model = "gemini-2.5-flash-preview-04-17"
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="""this is gemini code"""),
            ],
        ),
        types.Content(
            role="model",
            parts=[
                types.Part.from_text(text="""I will begin by performing a Google search for \"Gemini code\" to understand what the user might be referring to.
Then, I will analyze the search results to determine if \"Gemini code\" relates to a specific programming language, a software project, a redeemable code for Google's Gemini AI, or something else entirely.
Finally, I will answer the user's statement \"this is gemini code\" based on the information gathered from the Google search."""),
            ],
        ),
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="""are you capable of searching the web?"""),
            ],
        ),
    ]
    tools = [
        types.Tool(google_search=types.GoogleSearch()),
    ]
    generate_content_config = types.GenerateContentConfig(
        tools=tools,
        response_mime_type="text/plain",
    )

    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=generate_content_config,
    ):
        print(chunk.text, end="")

if __name__ == "__main__":
    generate()
