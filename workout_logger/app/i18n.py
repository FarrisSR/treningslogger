from __future__ import annotations

from flask import g


TRANSLATIONS: dict[str, dict[str, str]] = {
    "nb": {
        "nav.home": "Hjem",
        "nav.new_workout": "Ny økt",
        "nav.plan_builder": "Treningsøkt bygger",
        "nav.hiit": "HIIT / Tabata",
        "nav.stats": "Statistikk",
        "nav.json": "JSON",
        "nav.csv": "CSV",
        "nav.excel": "Excel",
        "nav.import": "Import",
        "nav.logout": "Logg ut",
        "lang.label": "Språk",
        "lang.norwegian": "Norsk",
        "lang.english": "Engelsk",
        "workouts.title": "Økter",
        "workouts.recent": "Nylige økter",
        "workouts.date": "Dato",
        "workouts.title_col": "Tittel",
        "workouts.plan": "Plan",
        "workouts.none": "Ingen økter ennå.",
        "workouts.quick_actions": "Hurtighandlinger",
        "workouts.create": "Opprett økt",
        "workouts.create_plan": "Opprett plan",
        "workouts.start_from_plan": "Start fra plan",
        "stats.title": "Statistikk",
        "stats.weekly_volume": "Ukentlig volum",
        "stats.estimated_1rm": "Estimert 1RM (Epley)",
        "stats.weekly_time": "Ukentlig tidsarbeid (sekunder)",
        "stats.exercise_overview": "Oversikt per øvelse",
        "stats.no_exercise_stats": "Ingen øvelsesstatistikk ennå.",
        "stats.col.exercise": "Øvelse",
        "stats.col.sets": "Sett",
        "stats.col.total_reps": "Totale reps",
        "stats.col.avg_reps": "Snitt reps/sett",
        "stats.col.best_weight": "Beste vekt (kg)",
        "stats.col.last_weight": "Siste vekt (kg)",
        "stats.col.total_time": "Total tid",
        "stats.col.avg_rpe": "Snitt RPE",
    },
    "en": {
        "nav.home": "Home",
        "nav.new_workout": "Ny økt",
        "nav.plan_builder": "Workout Builder",
        "nav.hiit": "HIIT / Tabata",
        "nav.stats": "Stats",
        "nav.json": "JSON",
        "nav.csv": "CSV",
        "nav.excel": "Excel",
        "nav.import": "Import",
        "nav.logout": "Logout",
        "lang.label": "Language",
        "lang.norwegian": "Norwegian",
        "lang.english": "English",
        "workouts.title": "Økter",
        "workouts.recent": "Nylige økter",
        "workouts.date": "Date",
        "workouts.title_col": "Title",
        "workouts.plan": "Plan",
        "workouts.none": "No workouts yet.",
        "workouts.quick_actions": "Quick Actions",
        "workouts.create": "Create workout",
        "workouts.create_plan": "Create plan",
        "workouts.start_from_plan": "Start from plan",
        "stats.title": "Stats",
        "stats.weekly_volume": "Weekly Volume",
        "stats.estimated_1rm": "Estimated 1RM (Epley)",
        "stats.weekly_time": "Weekly Timed Work (Seconds)",
        "stats.exercise_overview": "Per Exercise Overview",
        "stats.no_exercise_stats": "No exercise stats yet.",
        "stats.col.exercise": "Exercise",
        "stats.col.sets": "Sets",
        "stats.col.total_reps": "Total Reps",
        "stats.col.avg_reps": "Avg Reps/Set",
        "stats.col.best_weight": "Best Weight (kg)",
        "stats.col.last_weight": "Last Weight (kg)",
        "stats.col.total_time": "Total Time",
        "stats.col.avg_rpe": "Avg RPE",
    },
}


def get_language() -> str:
    profile = getattr(g, "current_user_profile", None)
    if profile and getattr(profile, "language", None) in {"nb", "en"}:
        return profile.language
    return "nb"


def translate(key: str) -> str:
    lang = get_language()
    if key in TRANSLATIONS.get(lang, {}):
        return TRANSLATIONS[lang][key]
    if key in TRANSLATIONS.get("nb", {}):
        return TRANSLATIONS["nb"][key]
    return key
