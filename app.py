from __future__ import annotations

from dotenv import load_dotenv
from openai import OpenAI
import json
import os
import requests
import yaml
from pathlib import Path
import gradio as gr


ME_DIR = Path(__file__).resolve().parent / "me"


def _load_me_yaml_chunks(me_dir: Path) -> tuple[str, str]:
    """Load all YAML documents under me_dir; return (person_name, combined text for the LLM)."""
    paths = sorted(me_dir.glob("*.yml")) + sorted(me_dir.glob("*.yaml"))
    if not paths:
        raise FileNotFoundError(f"No .yml or .yaml files found in {me_dir}")

    name = None
    chunks: list[str] = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and data.get("document_type") == "profile_summary":
            n = data.get("name")
            if isinstance(n, str) and n.strip():
                name = n.strip()
        if data is None:
            chunks.append(f"### {path.name}\n\n(empty file)\n")
            continue
        dumped = yaml.dump(
            data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )
        chunks.append(f"### {path.name}\n\n{dumped.strip()}\n")

    return name or "this person", "\n\n---\n\n".join(chunks)


load_dotenv(override=True)

def push(text):
    requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "token": os.getenv("PUSHOVER_TOKEN"),
            "user": os.getenv("PUSHOVER_USER"),
            "message": text,
        }
    )


def record_user_details(email, name="Name not provided", notes="not provided"):
    push(f"Recording {name} with email {email} and notes {notes}")
    return {"recorded": "ok"}

def record_unknown_question(question):
    push(f"Recording {question}")
    return {"recorded": "ok"}

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
            }
            ,
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
    "description": "REQUIRED before you tell the user you lack information: call this with the user's exact question whenever the structured profile documents below do not clearly and explicitly contain the answer (including patents, side projects, personal facts, or anything not stated in the docs). Call it in the same API turn as your first response—output only this tool call, no user-facing text, until after the tool result returns.",
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


class Me:

    def __init__(self):
        self.openai = OpenAI()
        self.name, self.structured_context = _load_me_yaml_chunks(ME_DIR)


    def handle_tool_call(self, tool_calls):
        results = []
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            print(f"Tool called: {tool_name}", flush=True)
            tool = globals().get(tool_name)
            result = tool(**arguments) if tool else {}
            results.append({"role": "tool","content": json.dumps(result),"tool_call_id": tool_call.id})
        return results
    
    def system_prompt(self):
        system_prompt = f"You are acting as {self.name}. You are answering questions on {self.name}'s website, \
particularly questions related to {self.name}'s career, background, skills and experience. \
Your responsibility is to represent {self.name} for interactions on the website as faithfully as possible. \
You are given structured profile documents below covering summaries, skills, and projects—use them as the sole source of truth to answer questions. \
Be professional and engaging, as if talking to a potential client or future employer who came across the website. \
\n## Mandatory tool use when the answer is missing\n\
If you cannot answer solely from those documents (the information is absent, unclear, or not explicit), you MUST call `record_unknown_question` with the user's question before you say you don't know. \
On that step, respond with ONLY the tool call—no assistant message text. After the tool returns, write your polite reply to the user. \
This applies to every topic (patents, employers, dates, etc.), not only career questions. \
If the user is engaging in discussion, try to steer them towards getting in touch via email; ask for their email and record it using your record_user_details tool. "

        system_prompt += f"\n\n## Structured profile documents:\n{self.structured_context}\n\n"
        system_prompt += f"With this context, please chat with the user, always staying in character as {self.name}."
        return system_prompt

    @staticmethod
    def _history_to_messages(history):
        """Gradio ChatInterface passes [[user, assistant], ...]; OpenAI expects role/content dicts."""
        if not history:
            return []
        if isinstance(history[0], dict):
            return list(history)
        out = []
        for turn in history:
            if not isinstance(turn, (list, tuple)) or len(turn) != 2:
                continue
            user_msg, assistant_msg = turn
            if user_msg is not None and str(user_msg).strip():
                out.append({"role": "user", "content": user_msg})
            if assistant_msg is not None and str(assistant_msg).strip():
                out.append({"role": "assistant", "content": assistant_msg})
        return out

    @staticmethod
    def _assistant_admits_missing_docs(text: str) -> bool:
        """Heuristic fallback when the model answers in text but should have recorded the question."""
        t = text.lower()
        return any(
            phrase in t
            for phrase in (
                "don't have information",
                "do not have information",
                "don't have any information",
                "no information about",
                "not have information about",
                "don't have details",
                "no details about",
                "isn't in the profile",
                "is not in the profile",
                "not mentioned in the",
                "nothing in the documents",
                "not covered in",
            )
        )

    def chat(self, message, history):
        user_question = message
        prior = self._history_to_messages(history)
        messages = [{"role": "system", "content": self.system_prompt()}] + prior + [{"role": "user", "content": message}]
        done = False
        recorded_unknown = False
        while not done:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=tools,
                parallel_tool_calls=False,
            )
            if response.choices[0].finish_reason == "tool_calls":
                assistant_msg = response.choices[0].message
                tool_calls = assistant_msg.tool_calls
                for tc in tool_calls:
                    if tc.function.name == "record_unknown_question":
                        recorded_unknown = True
                results = self.handle_tool_call(tool_calls)
                messages.append(assistant_msg)
                messages.extend(results)
            else:
                done = True
        final = response.choices[0].message
        final_text = final.content or ""
        if not recorded_unknown and final_text and self._assistant_admits_missing_docs(final_text):
            record_unknown_question(user_question)
        return final.content
    

if __name__ == "__main__":
    me = Me()
    gr.ChatInterface(me.chat).launch()
    