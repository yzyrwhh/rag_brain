import os

from altair.theme import enable
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from sympy.physics.units import temperature

load_dotenv()

def get_llm_client():
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_API_BASE")
        model_name = os.getenv("ITEM_MODEL")

        client = ChatOpenAI(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature = 0.1,
            extra_body={
                "enable——thinking" : False,
            }
        )
        return client
    except Exception as e:
        raise e

