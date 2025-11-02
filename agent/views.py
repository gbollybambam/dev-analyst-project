import json
import os
import uuid
from datetime import datetime, timezone
import requests 

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


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
    """Fetches public repository data for a given GitHub username (limited to 10 for speed)."""
    api_url = f"https://api.github.com/users/{username}/repos?per_page=10" 
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
        return {"error": f"Could not fetch GitHub data for '{username}'.", "details": str(e)}

def get_gemini_analysis(username: str, github_data: dict) -> str:
    """Uses the lightweight requests library to call the fixed Gemini API endpoint."""
    if not GEMINI_API_KEY:
        return "Error: GEMINI_API_KEY is not set. The server is misconfigured."

    api_url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    github_data_json_string = json.dumps(github_data, indent=2)
    prompt_text = GEMINI_PROMPT_TEMPLATE.format(
        github_data=github_data_json_string,
        username=username
    )

    payload = {
        "contents": [
            {"parts": [{"text": prompt_text}]}
        ]
    }
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()

        response_json = response.json()
        analysis_text = response_json['candidates'][0]['content']['parts'][0]['text']
        return analysis_text

    except requests.exceptions.RequestException as e:
        print(f"---! ERROR calling Gemini (HTTP) !---: {e}")
        return f"Error: The AI analysis API failed. Details: {e.response.text}"
    except (KeyError, IndexError) as e:
        print(f"---! ERROR parsing Gemini response !---: {e}")
        return f"Error: The AI analysis returned an unexpected format."
    except Exception as e:
        print(f"---! UNKNOWN ERROR in get_gemini_analysis !---: {e}")
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


            user_text = ""

            for part in parts:
                if part.get('kind') == 'text' and part.get('text'):
                    user_text = part['text'].strip().lower() 

            if user_text.startswith("gbollybambam "):
                 user_text = user_text.replace("gbollybambam ", "").strip()
            if user_text.startswith("@devanalyst "):
                 user_text = user_text.replace("@devanalyst ", "").strip()
            

            
            if not user_text:
                analysis_text = "**Error:** Invalid request. Please provide a GitHub username immediately after @DevAnalyst."
                github_data = {} 
            
            elif user_text in ["help", "hi", ""]:
                analysis_text = ""
                github_data = {} 
            else:
                github_data = get_github_data(user_text)
                analysis_text = get_gemini_analysis(user_text, github_data)


            task_id = message.get('taskId', str(uuid.uuid4()))
            context_id = params.get('contextId', task_id)
            agent_message_part = { "kind": "text", "text": analysis_text }
            response_message = {
                "kind": "message", "role": "agent", "parts": [agent_message_part],
                "messageId": str(uuid.uuid4()), "taskId": task_id
            }
            result_payload = {
                "id": task_id, "contextId": context_id, 
                "status": {"state": "completed", "timestamp": datetime.now(timezone.utc).isoformat(), "message": response_message},
                "artifacts": [{"artifactId": str(uuid.uuid4()), "name": "github_raw_data", "parts": [{"kind": "data", "data": github_data}]}],
                "history": [], "kind": "task"
            }
            response = {"jsonrpc": "2.0", "id": rpc_id, "result": result_payload}

            return JsonResponse(response, status=200)

        except Exception as e:
            print(f"---! CRITICAL ERROR in DevAnalystView !---: {e}")

            error_text = f"I'm sorry, I ran into a critical server error. Please tell the admin: {str(e)}"

            task_id = str(uuid.uuid4())
            context_id = str(uuid.uuid4())
            if 'message' in locals() and message:
                 task_id = message.get('taskId', str(uuid.uuid4()))
            if 'params' in locals() and params:
                context_id = params.get('contextId', task_id)
            
            agent_message_part = { "kind": "text", "text": error_text }
            response_message = {
                "kind": "message", "role": "agent", "parts": [agent_message_part],
                "messageId": str(uuid.uuid4()), "taskId": task_id
            }
            result_payload = {
                "id": task_id, "contextId": context_id,
                "status": {"state": "completed", "timestamp": datetime.now(timezone.utc).isoformat(), "message": response_message},
                "artifacts": [], "history": [], "kind": "task"
            }
            response = {"jsonrpc": "2.0", "id": rpc_id or str(uuid.uuid4()), "result": result_payload}
            
            return JsonResponse(response, status=200)