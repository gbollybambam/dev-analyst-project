import json
import os
import uuid

import requests
import google.generativeai as genai

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("WARNING: GEMINI_API_KEY is not set. The AI will not work.")

GEMINI_PROMPT_TEMPLATE = """
You are a '10x' Senior Engineering Manager and a hiring expert. Your only job is to analyze a developer's potential based *only* on the following JSON list of their public repositories.

Do not make up information. Use only the data provided.

**JSON Data:**
{github_data}

**User's Request:**
Analyze: {username}

**Your Analysis (Use this exact format):**
**Analysis for:** `{username}`

**Estimated Seniority:** [Junior / Mid-Level / Senior / Principal / Legendary]
**Primary Specialties:** [List of top 3 languages/skills, e.g., "Python (Django)", "TypeScript (React)", "DevOps (Docker)"]
**Key Insights:**
* [Your 1-2 bullet point analysis of their projects. e.g., "High number of forked repos with no original commits, suggests they are a learner." or "Multiple high-star original projects in React, shows strong expertise." or "Profile shows a focus on backend systems and infrastructure."]

**Recommendation:** [A 1-sentence hiring recommendation.]
"""

def get_github_data(username: str) -> dict:
    api_url = f"https://api.github.com/users/{username}/repos?per_page=20"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()

        repos = response.json()
        simplified_repos = [
            {
                "name": repo.get("name"),
                "stars": repo.get("stargazers_count"),
                "forks": repo.get("forks_count"),
                "language": repo.get("language"),
                "description": repo.get("description"),
                "is_fork": repo.get("fork")
            } for repo in repos
        ]

        return simplified_repos
    
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Github data: {e}")
        return {"error": "Could not fetch Github data for this user. They may not exist.", "details": str(e)}

def get_gemini_analysis(username: str, github_data: dict) -> str:
    if not GEMINI_API_KEY:
        return "Error: GEMINI_API_KEY is not set. The server is misconfigured. please contact the administrator."
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')
        github_data_json_string = json.dumps(github_data, indent=2)

        prompt = GEMINI_PROMPT_TEMPLATE.format(
            github_data=github_data_json_string,
            username=username
        )
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error generating Gemini analysis: {e}")
        return f"Error: The AI analysis failed. Details: {str(e)}"
    

@method_decorator(csrf_exempt, name='dispatch')
class DevAnalystView(View):
    def post(self, request: HttpRequest, *args, **kwargs):
        rpc_id = None

        try:
            data = json.loads(request.body)
            rpc_id = data.get('id', str(uuid.uuid4()))
            params = data.get('params', {})
            message = params.get('message', {})
            parts = message.get('parts', [])

            if not parts or parts[0].get('kind') != 'text':
                raise ValueError("Invalid request format: 'parts[0].text' not found. ")
            username = parts[0]['text'].strip()

            github_data = get_github_data(username)

            analysis_text = get_gemini_analysis(username, github_data)

            task_id = message.get('taskId', str(uuid.uuid4()))
            context_id = params.get('contextId', task_id)

            agent_message_part = {
                "kind": "text",
                "text": analysis_text
            }

            response_message = {
                "kind": "message",
                "role": "agent",
                "parts": [agent_message_part],
                "messageId": str(uuid.uuid4()),
                "taskId": task_id
            }

            result_payload = {
                "id": task_id,
                "contextId": context_id,
                "status": {
                    "state": "completed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": response_message
                },
                "artifacts": [
                    {
                        "artifactId": str(uuid.uuid4()),
                        "name": "github_raw_data",
                        "parts": [
                            {
                                "kind": "data",
                                "data": github_data
                            }
                        ]
                    }
                ],
                "history": [],
                "kind": "task"
            }

            response = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": result_payload
            }

            return JsonResponse(response)
        except Exception as e:
            print(f"---!Error in DevAnalystView !---: {e}")

            error_payload = {
                "code": -32603,
                "message": "Internal server error",
                "data": {"details": str(e)}
            }

            response = {
                "jsonrpc": "2.0",
                "id": rpc_id or str(uuid.uuid4()),
                "error": error_payload
            }

            return JsonResponse(response, status=500)