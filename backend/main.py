from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from datetime import date, timedelta
import os
import base64
import requests

# Load environment variables from the .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    # Fallback if python-dotenv is not installed
    pass

app = FastAPI()

# Configure CORS (Cross-Origin Resource Sharing) for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "GitStatCard"
    }

    token = os.getenv("GITHUB_TOKEN")
    # Avoid using standard dummy values or placeholder values that fail authentication
    if token and token.strip() and not token.startswith("github_pat_antigravity") and token != "your_github_token_here":
        headers["Authorization"] = f"Bearer {token}"

    return headers
def get_total_stars(username: str):
    total_stars = 0
    page = 1

    while True:
        url = f"https://api.github.com/users/{username}/repos"
        response = requests.get(
            url,
            headers=github_headers(),
            params={"per_page": 100, "page": page, "type": "owner"},
            timeout=10
        )

        if response.status_code != 200:
            return 0

        repos = response.json()

        if not repos:
            break

        total_stars += sum(repo["stargazers_count"] for repo in repos)
        page += 1

    return total_stars



def get_contribution_stats(username: str):
    token = os.getenv("GITHUB_TOKEN")

    # GraphQL API requires a valid token; skip and return empty stats if none is set or if it's a dummy/placeholder token
    if not token or not token.strip() or token.startswith("github_pat_antigravity") or token == "your_github_token_here":
        return {
            "commits": 0,
            "current_streak": 0,
            "max_streak": 0
        }

    today = date.today()
    start_date = today - timedelta(days=364)

    query = """
    query($username: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $username) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """

    variables = {
        "username": username,
        "from": f"{start_date.isoformat()}T00:00:00Z",
        "to": f"{today.isoformat()}T23:59:59Z"
    }

    response = requests.post(
        "https://api.github.com/graphql",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": query, "variables": variables},
        timeout=15
    )

    print("DEBUG: GraphQL Request status code:", response.status_code)
    if response.status_code != 200:
        print("DEBUG: GraphQL Request raw error response:", response.text)
        return {
            "commits": 0,
            "current_streak": 0,
            "max_streak": 0
        }

    result = response.json()
    if result.get("errors"):
        print("DEBUG: GraphQL query errors:", result.get("errors"))
    if not result.get("data", {}).get("user"):
        print("DEBUG: GraphQL user data is empty:", result.get("data"))

    if result.get("errors") or not result.get("data", {}).get("user"):
        return {
            "commits": 0,
            "current_streak": 0,
            "max_streak": 0
        }

    collection = result["data"]["user"]["contributionsCollection"]
    total_commits = collection["totalCommitContributions"]

    days = []
    for week in collection["contributionCalendar"]["weeks"]:
        days.extend(week["contributionDays"])

    days.sort(key=lambda day: day["date"])

    max_streak = 0
    running_streak = 0

    for day in days:
        if day["contributionCount"] > 0:
            running_streak += 1
            max_streak = max(max_streak, running_streak)
        else:
            running_streak = 0

    contribution_by_date = {
        day["date"]: day["contributionCount"]
        for day in days
    }

    streak_date = today

    if contribution_by_date.get(streak_date.isoformat(), 0) == 0:
        streak_date -= timedelta(days=1)

    current_streak = 0

    while contribution_by_date.get(streak_date.isoformat(), 0) > 0:
        current_streak += 1
        streak_date -= timedelta(days=1)

    return {
        "commits": total_commits,
        "current_streak": current_streak,
        "max_streak": max_streak
    }
@app.get("/")
def home():
    return {
        "message": "GitStatCard backend is running"
    }
@app.get("/api/user/{username}")
def get_user(username: str):
    url = f"https://api.github.com/users/{username}"
    response = requests.get(url, headers=github_headers(), timeout=10)
    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="GitHub user not found"
        )
    if response.status_code == 403:
        raise HTTPException(
            status_code=403,
            detail="GitHub API rate limit exceeded. Set a valid GITHUB_TOKEN and restart the server."
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"GitHub API error: {response.text}"
        )
    data = response.json()
    return {
    "name": data.get("name") or data["login"],
    "username": data["login"],
    "profile_picture": data["avatar_url"],
    "total_repos": data["public_repos"],
    "followers": data["followers"],
    "following": data["following"]
}
@app.get("/api/card/{username}")
def get_card(username: str, theme: str = "github-dark"):
    # Validate theme name to prevent path traversal
    allowed_themes = {"github-dark", "github-futuristic", "github-cyber-center", "github-cyber-portrait"}
    if theme not in allowed_themes:
        theme = "github-dark"

    url = f"https://api.github.com/users/{username}"
    response = requests.get(url, headers=github_headers(), timeout=10)
    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="GitHub user not found"
        )
    if response.status_code == 403:
        raise HTTPException(
            status_code=403,
            detail="GitHub API rate limit exceeded. Set a valid GITHUB_TOKEN and restart the server."
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"GitHub API error: {response.text}"
        )
    data = response.json()
    avatar_response = requests.get(data["avatar_url"], timeout=10)
    profile_picture = data["avatar_url"]

    if avatar_response.status_code == 200:
        avatar_base64 = base64.b64encode(avatar_response.content).decode("utf-8")
        content_type = avatar_response.headers.get("Content-Type", "image/png")
        profile_picture = f"data:{content_type};base64,{avatar_base64}"

    contribution_stats = get_contribution_stats(username)
    total_stars = get_total_stars(username)
    svg_path = Path(__file__).parent.parent / "cards" / f"{theme}.svg"
    svg = svg_path.read_text(encoding="utf-8")
    svg = svg.replace("{{NAME}}", data.get("name") or data["login"])
    svg = svg.replace("{{USERNAME}}", data["login"])
    svg = svg.replace("{{PROFILE_PICTURE}}", profile_picture)
    svg = svg.replace("{{TOTAL_REPOS}}", str(data["public_repos"]))
    svg = svg.replace("{{FOLLOWERS}}", str(data["followers"]))
    svg = svg.replace("{{COMMITS}}", str(contribution_stats["commits"]))
    svg = svg.replace("{{STARS}}", str(total_stars))
    svg = svg.replace("{{CURRENT_STREAK}}", str(contribution_stats["current_streak"]))
    svg = svg.replace("{{MAX_STREAK}}", str(contribution_stats["max_streak"]))

    return Response(
        content=svg,
        media_type="image/svg+xml"
    )