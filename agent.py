# agent.py
"""
ConciergeChef - ADK-style Python agent scaffold (single-file)
This file provides:
- Multi-agent structure (Master, Planner, ShoppingList, Scheduler)
- Tool interfaces (recipe search, price lookup, calendar) with mock implementations
- Simple in-memory session & memory bank
- Logging and evaluation hooks
Note: Replace mock tools with real API calls as needed. Do NOT include API keys.
"""

import json
import logging
import random
import datetime
from typing import List, Dict, Any

# -------- logging / observability --------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ConciergeChef")

# -------- simple memory bank & session --------
class MemoryBank:
    def __init__(self, filename="data/memory.json"):
        self.filename = filename
        try:
            with open(self.filename, "r") as f:
                self.store = json.load(f)
        except Exception:
            self.store = {"users": {}}

    def get_user(self, user_id: str):
        return self.store["users"].get(user_id, {"preferences": {}, "pantry": [], "history": []})

    def update_user(self, user_id: str, data: Dict[str, Any]):
        self.store["users"].setdefault(user_id, {}).update(data)
        self._persist()

    def _persist(self):
        with open(self.filename, "w") as f:
            json.dump(self.store, f, indent=2)

# -------- mock tools --------
class RecipeTool:
    """Mock recipe search tool. Replace with real API integration."""
    def __init__(self, recipes_file="data/sample_recipes.json"):
        try:
            with open(recipes_file) as f:
                self.recipes = json.load(f)
        except Exception:
            # minimal sample fallback
            self.recipes = [
                {"id": "r1", "title": "Beans & Rice Bowl", "ingredients": ["rice", "canned beans", "tomato"], "diet": "vegetarian", "time": 25},
                {"id": "r2", "title": "Tomato Pasta", "ingredients": ["pasta", "tomato", "olive oil"], "diet": "vegetarian", "time": 30},
                {"id": "r3", "title": "Veg Stir Fry", "ingredients": ["mixed veg", "soy sauce", "rice"], "diet": "vegetarian", "time": 20}
            ]

    def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        # query contains: diet, pantry, max_time
        diet = query.get("diet")
        pantry = set(query.get("pantry", []))
        max_time = query.get("max_time", 60)
        results = []
        for r in self.recipes:
            if diet and r.get("diet") != diet:
                continue
            if r.get("time", 999) > max_time:
                continue
            # simple pantry match score
            pantry_overlap = len(pantry.intersection(r.get("ingredients", [])))
            score = pantry_overlap + random.random()  # small randomness
            r_copy = r.copy()
            r_copy["pantry_overlap"] = pantry_overlap
            r_copy["score"] = score
            results.append(r_copy)
        results.sort(key=lambda x: (-x["score"], x["time"]))
        return results

class PriceTool:
    """Mock price lookup (returns estimated price per ingredient)."""
    def estimate(self, ingredients: List[str]) -> Dict[str, float]:
        # naive price map
        base = {"rice": 2.5, "canned beans": 1.2, "tomato": 0.7, "pasta": 1.0, "olive oil": 3.0, "mixed veg": 2.0, "soy sauce": 1.0}
        return {ing: base.get(ing, 1.5) for ing in ingredients}

class CalendarTool:
    """Mock calendar event creator - prints and returns an event id."""
    def create_event(self, user_id: str, title: str, dt: datetime.datetime, notes: str = "") -> Dict[str, Any]:
        event_id = f"ev_{random.randint(1000, 9999)}"
        logger.info(f"[Calendar] create_event user={user_id} event_id={event_id} title={title} dt={dt.isoformat()}")
        return {"event_id": event_id, "title": title, "datetime": dt.isoformat(), "notes": notes}

# -------- agents --------
class PlannerAgent:
    def __init__(self, recipe_tool: RecipeTool, price_tool: PriceTool):
        self.recipe_tool = recipe_tool
        self.price_tool = price_tool

    def generate_weekly_plan(self, user_profile: Dict[str, Any], pantry: List[str], constraints: Dict[str, Any]):
        """Return a list of 7 meals (dinner) with metadata and estimated cost."""
        diet = user_profile.get("diet", "vegetarian")
        max_time = constraints.get("max_time", 60)
        budget = constraints.get("budget", 60)
        logger.info(f"[Planner] Generating plan diet={diet} budget={budget} max_time={max_time}")

        # For simplicity: pick top N unique recipes from search
        all_candidates = self.recipe_tool.search({"diet": diet, "pantry": pantry, "max_time": max_time})
        plan = []
        i = 0
        # loop agent behavior: try to ensure pantry reuse >= 40% by re-scoring / re-running
        while len(plan) < 7 and i < max(7, len(all_candidates)*2):
            if i < len(all_candidates):
                candidate = all_candidates[i].copy()
                candidate["estimated_cost"] = sum(self.price_tool.estimate(candidate["ingredients"]).values())
                plan.append(candidate)
            else:
                # fallback: random pick
                plan.append(random.choice(self.recipe_tool.recipes))
            i += 1
        plan = plan[:7]

        # compact cost check and simple re-run if budget exceeded
        total_estimated = sum([p.get("estimated_cost", 3.0) for p in plan])
        logger.info(f"[Planner] Estimated weekly dinner cost: {total_estimated:.2f}")
        # Minimal loop optimization: if over budget, replace highest-cost meal with lower-cost candidate
        attempts = 0
        while total_estimated > budget and attempts < 5:
            plan.sort(key=lambda x: x.get("estimated_cost", 0), reverse=True)
            # try to find a cheaper candidate
            for c in all_candidates[::-1]:
                if c["id"] not in [p["id"] for p in plan]:
                    c_copy = c.copy()
                    c_copy["estimated_cost"] = sum(self.price_tool.estimate(c_copy["ingredients"]).values())
                    plan[0] = c_copy
                    break
            total_estimated = sum([p.get("estimated_cost", 3.0) for p in plan])
            attempts += 1
            logger.info(f"[Planner] Re-optimizing attempt {attempts}, cost={total_estimated:.2f}")

        # scoring & metadata
        for p in plan:
            p["pantry_overlap"] = len(set(p.get("ingredients", [])).intersection(set(pantry)))
        return {"plan": plan, "estimated_total": total_estimated}

class ShoppingListAgent:
    def __init__(self, price_tool: PriceTool):
        self.price_tool = price_tool

    def build_shopping_list(self, plan: List[Dict[str, Any]], pantry: List[str]):
        # aggregate ingredients and subtract pantry
        agg = {}
        for meal in plan:
            for ing in meal.get("ingredients", []):
                agg[ing] = agg.get(ing, 0) + 1
        shopping = {ing: qty for ing, qty in agg.items() if ing not in pantry}
        # estimate prices
        prices = self.price_tool.estimate(list(shopping.keys()))
        total = sum(prices.values())
        return {"items": shopping, "prices": prices, "estimated_total": total}

class SchedulerAgent:
    def __init__(self, calendar_tool: CalendarTool):
        self.calendar_tool = calendar_tool

    def schedule_meals(self, user_id: str, plan: List[Dict[str, Any]], start_date: datetime.date):
        events = []
        date = start_date
        for meal in plan:
            dt = datetime.datetime.combine(date, datetime.time(19, 0))  # default dinner at 7 PM
            ev = self.calendar_tool.create_event(user_id, f"Cook: {meal['title']}", dt, notes="Prep time: {} mins".format(meal.get("time", 30)))
            events.append(ev)
            date += datetime.timedelta(days=1)
        return events

# -------- Master orchestration --------
class ConciergeChef:
    def __init__(self, memory: MemoryBank):
        self.memory = memory
        self.recipe_tool = RecipeTool()
        self.price_tool = PriceTool()
        self.calendar_tool = CalendarTool()
        self.planner = PlannerAgent(self.recipe_tool, self.price_tool)
        self.shopper = ShoppingListAgent(self.price_tool)
        self.scheduler = SchedulerAgent(self.calendar_tool)

    def handle_request(self, user_id: str, request: Dict[str, Any]):
        # Input: request contains constraints and an action 'plan_week'
        user = self.memory.get_user(user_id)
        pantry = user.get("pantry", request.get("pantry", []))
        preferences = user.get("preferences", {})
        # Merge provided constraints
        constraints = request.get("constraints", {"budget": 60, "max_time": 60})
        # Planner Agent
        result = self.planner.generate_weekly_plan({**preferences, **request.get("profile", {})}, pantry, constraints)
        plan = result["plan"]
        summary = {
            "plan": [{"id": p["id"], "title": p["title"], "ingredients": p["ingredients"], "estimated_cost": p.get("estimated_cost", 0)} for p in plan],
            "estimated_total": result["estimated_total"]
        }
        # Shopping List Agent
        shopping = self.shopper.build_shopping_list(plan, pantry)
        # Scheduler optionally
        schedule = []
        if request.get("auto_schedule", False):
            today = datetime.date.today()
            schedule = self.scheduler.schedule_meals(user_id, plan, today + datetime.timedelta(days=1))
        # Save session & memory updates
        self.memory.update_user(user_id, {"last_plan": summary, "last_shopping": shopping})
        logger.info(f"[Master] Completed plan for user {user_id}. Estimated total: {summary['estimated_total']:.2f}")
        return {"summary": summary, "shopping": shopping, "schedule": schedule}

# -------- simple demo run --------
if __name__ == "__main__":
    # create minimal memory storage and sample pantry
    mem = MemoryBank(filename="data/memory.json")
    # ensure sample user
    user_id = "alice@example.com"
    mem.update_user(user_id, {"preferences": {"diet": "vegetarian"}, "pantry": ["rice", "canned beans", "tomato"]})
    chef = ConciergeChef(mem)
    request = {
        "action": "plan_week",
        "profile": {},
        "pantry": ["rice", "canned beans", "tomato"],
        "constraints": {"budget": 40, "max_time": 45},
        "auto_schedule": True
    }
    out = chef.handle_request(user_id, request)
    print(json.dumps(out, indent=2))
