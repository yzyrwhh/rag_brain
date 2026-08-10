import os

import dotenv

dotenv.load_dotenv()

dashscope_base_url = os.environ.get("MCP_DASHSCOPE_BASE_URL")
api_key = os.environ.get("OPENAI_API_KEY")

