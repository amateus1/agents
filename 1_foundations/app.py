import gradio as gr
from dotenv import load_dotenv
from openai import OpenAI
import json
import os
import requests
import re
from pypdf import PdfReader
import resend

# Load environment variables
load_dotenv()

# Push notification function (using Pushover)
def push(text):
    requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "token": os.getenv("PUSHOVER_TOKEN"),
            "user": os.getenv("PUSHOVER_USER"),
            "message": text,
        }
    )

# Functions to record user details or unknown questions
def record_user_details(email, name="Name not provided", notes="not provided"):
    push(f"Recording {name} with email {email} and notes {notes}")
    return {"recorded": "ok"}

def record_unknown_question(question):
    push(f"Recording {question}")
    return {"recorded": "ok"}

# Example tool configurations for the system
record_user_details_json = {
    "name": "record_user_details",
    "description": "Use this tool to record that a user is interested in being in touch and provided an email address",
    "parameters": {
        "type": "object",
        "properties": {
            "email": {
                "type": "string",
                "description": "The email address of this user"
            },
            "name": {
                "type": "string",
                "description": "The user's name, if they provided it"
            },
            "notes": {
                "type": "string",
                "description": "Any additional information about the conversation that's worth recording to give context"
            }
        },
        "required": ["email"],
        "additionalProperties": False
    }
}

record_unknown_question_json = {
    "name": "record_unknown_question",
    "description": "Always use this tool to record any question that couldn't be answered as you didn't know the answer",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question that couldn't be answered"
            },
        },
        "required": ["question"],
        "additionalProperties": False
    }
}

tools = [{"type": "function", "function": record_user_details_json},
         {"type": "function", "function": record_unknown_question_json}]

# Function to send email via Resend API using the API key from the .env file
def send_email_via_resend(to_email, subject, body):
    api_key = os.getenv("RESEND_API_KEY")  # Fetch the API key from the .env file

    if not api_key:
        raise ValueError("Resend API key is missing. Please ensure it's in the .env file.")

    # Initialize Resend client
    client = resend.Client(api_key=api_key)

    # Create and send the email
    try:
        client.emails.send(
            from_="al@optimops.ai",  # Replace with your email
            to=[to_email],
            subject=subject,
            text=body
        )
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Error sending email: {e}")

# Define the Me class which handles the system prompt and chatbot responses
class Me:
    def __init__(self):
        self.openai = OpenAI()
        self.name = "Al Mateus"
        reader = PdfReader("me/linkedin.pdf")
        self.linkedin = ""
        for page in reader.pages:
            text = page.extract_text()
            if text:
                self.linkedin += text
        with open("me/summary.txt", "r", encoding="utf-8") as f:
            self.summary = f.read()

    def handle_tool_call(self, tool_calls):
        results = []
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            tool = globals().get(tool_name)
            result = tool(**arguments) if tool else {}
            results.append({"role": "tool", "content": json.dumps(result), "tool_call_id": tool_call.id})
        return results

    def system_prompt(self):
        system_prompt = f"You are acting as {self.name}. You are answering questions on {self.name}'s website, \
        particularly questions related to {self.name}'s career, background, skills and experience. \
        Your responsibility is to represent {self.name} for interactions on the website as faithfully as possible. \
        You are given a summary of {self.name}'s background and LinkedIn profile which you can use to answer questions. \
        Keep the tone professional yet human — confident, occasionally humorous, and globally aware. \
        Use casual analogies when useful (e.g., 'deploying a pipeline is like tuning a race car'). \
        If asked about personal interests, share fun facts: Hernan has 5 cats, 2 dogs, drives a Tesla M3P, \
        and once went scuba diving at night — because why not automate *and* live on the edge?"

        system_prompt += f"\n\n## Summary:\n{self.summary}\n\n## LinkedIn Profile:\n{self.linkedin}\n\n"
        system_prompt += f"With this context, please chat with the user, always staying in character as {self.name}."
        return system_prompt

    def chat(self, message, history):
        is_first_turn = len(history) == 0
        messages = [{"role": "system", "content": self.system_prompt()}]

        if is_first_turn:
            introduction = (
                "Hey there! I’m Hernan’s digital twin — trained on his global career, tech philosophies, "
                "and love for Thai food, Star Wars, and track-ready Teslas. "
                "Ask me anything about his work, journey, or how many cats is too many (hint: it’s more than 5)."
            )
            messages.append({"role": "system", "content": introduction})

        messages.append({"role": "user", "content": message})

        while True:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=tools
            )

            choice = response.choices[0]

            if choice.finish_reason == "tool_calls":
                messages.append(choice.message)
                messages.extend(self.handle_tool_call(choice.message.tool_calls))
            else:
                final_response = choice.message.content

                # Check if the message contains an email address
                email = self.extract_email(message)
                if email:
                    send_email_via_resend("al@optimops.ai", "New Contact Email", f"User email: {email}")  # Send email via Resend
                    final_response += (
                        "\n\n📬 Thanks for sharing your email! I'll get in touch with you shortly."
                    )

                # Add follow-up prompt if the user mentions contact
                contact_keywords = ["contact", "email", "reach", "connect", "get in touch", "how do I talk"]
                if any(kw in message.lower() for kw in contact_keywords):
                    final_response += (
                        "\n\n📬 Would you like to share your email so Hernan can follow up personally? "
                        "You can also contact him directly at **al@optimops.ai**."
                    )

                return final_response

    def extract_email(self, text):
        # Regex to extract emails from the text
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,4}"
        match = re.search(email_pattern, text)
        return match.group(0) if match else None

if __name__ == "__main__":
    me = Me()

    gr.ChatInterface(
        fn=me.chat,
        title="🤖 Meet Hernan 'Al' Mateus — Your Global AI, DevSecOps & Cloud Architect",
        description=( 
            "Welcome! I'm Hernan's digital twin — trained on his global career, MLOps mastery, love of Thai food, "
            "Star Wars, and GPT-powered systems. Ask me anything about his work, LLMOps projects, career journey, "
            "or how to scale AI across 3 clouds and 9 countries 🌏"
        ),
        examples=[
            ["Tell about his experience building a consulting practice?"],
            ["What kind of projects does Hernan lead?"],
            ["Tell me something personal about Hernan."],
            ["What is Hernan’s favorite tech stack?"],
            ["Tell me about Hernan's experience  with Azure?"]
        ],
        theme="soft",
        type="messages"
    ).launch()
