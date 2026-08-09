import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

def get_llm_client(json_mode: bool = False):
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_API_BASE")
        model_name = os.getenv("ITEM_MODEL")
        extra_body = {
            "enable_thinking": False,
        }
        if json_mode:
            extra_body["response_format"] = {"type": "json_object"}

        client = ChatOpenAI(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            extra_body=extra_body,
        )
        return client
    except Exception as e:
        raise e

