import json
import os
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st

st.set_page_config(page_title="ReleaseGuard", page_icon="🛡️", layout="wide")
st.title("ReleaseGuard")
st.caption("Compare releases. Inspect failures. Measure unusual performance.")

api = os.getenv("API_ORIGIN", "http://127.0.0.1:8000")
headers = {"X-API-Key": os.getenv("API_KEY", "")}


def request(method, path, **kwargs):
    try:
        response = httpx.request(method, api + path, headers=headers, timeout=10, **kwargs)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as error:
        st.error(f"Request failed: {error.response.text}")
    except httpx.RequestError:
        st.error("The monitor API is unavailable. Start the local services first.")
    return None


projects = request("GET", "/projects")
if projects is None:
    st.stop()
if not projects:
    st.info("Create the demonstration project to get started.")
    if st.button("Set up demo project", type="primary"):
        from scripts.demo import seed

        try:
            with httpx.Client(base_url=api, timeout=10, headers=headers) as client:
                seed(client)
            st.rerun()
        except httpx.HTTPError as error:
            st.error(str(error))
    st.stop()

project = st.sidebar.selectbox("Project", projects, format_func=lambda p: p["name"], key="project")
st.sidebar.caption("Checks use a controlled demonstration application.")
if st.sidebar.button("Refresh results"):
    st.rerun()
releases = request("GET", f"/projects/{project['id']}/releases") or []
history = request("GET", f"/projects/{project['id']}/history?limit=100") or []
tabs = st.tabs(["Run checks", "Results", "Compare releases", "ML evaluation"])

with tabs[0]:
    st.subheader("Test a release")
    if releases:
        with st.form("run"):
            release = st.selectbox(
                "Release", releases, format_func=lambda r: r["label"], key="release"
            )
            left, right = st.columns(2)
            windows = left.number_input("Measurement windows", 1, 10, 3)
            probes = right.number_input("Requests per endpoint per window", 1, 100, 25)
            st.caption("Default workload: concurrency 5, request deadline 0.3 seconds.")
            submitted = st.form_submit_button("Run checks", type="primary")
        if submitted:
            import uuid

            queued = request(
                "POST",
                "/runs",
                json={
                    "release_id": release["id"],
                    "idempotency_key": str(uuid.uuid4()),
                    "windows": windows,
                    "probes_per_window": probes,
                },
            )
            if queued:
                st.session_state["last_run"] = queued["id"]
                st.success(f"Run {queued['id']} queued. Open Results and refresh to follow it.")
    else:
        st.info("Register demo releases using python -m scripts.demo --seed-only.")

with tabs[1]:
    st.subheader("Run history")
    if history:
        labels = {r["id"]: r["label"] for r in releases}
        run_by_id = {run["id"]: run for run in history}
        selected_id = st.selectbox(
            "Run",
            list(run_by_id),
            format_func=lambda run_id: (
                f"#{run_id} · {labels.get(run_by_id[run_id]['release_id'])} · {run_by_id[run_id]['state']}"
            ),
            key="result_run_id",
        )
        result = request("GET", f"/runs/{selected_id}/report")
        if result:
            if result["state"] != "COMPLETED":
                st.info(f"State: {result['state']} · attempt {result['attempt']}")
                if result["error"]:
                    st.warning(result["error"])
            else:
                rows = []
                for endpoint in result["endpoints"]:
                    counts = endpoint["counts"]
                    rows.append(
                        {
                            "Endpoint": endpoint["path"],
                            "Requests": endpoint["samples"],
                            "Passed": counts["OK"],
                            "Contract failures": counts["CONTRACT_FAILURE"],
                            "HTTP errors": counts["HTTP_ERROR"],
                            "Timeouts": counts["TIMEOUT"],
                            "Network errors": counts["NETWORK_ERROR"],
                            "p95 (ms)": endpoint["p95_ms"],
                            "ML flags / scored": f"{endpoint['ml_flagged_windows']} / {endpoint['ml_scored_windows']}",
                        }
                    )
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
                for endpoint in result["endpoints"]:
                    with st.expander(f"Evidence: {endpoint['path']}"):
                        if endpoint["evidence"]:
                            st.dataframe(pd.DataFrame(endpoint["evidence"]), hide_index=True)
                        else:
                            st.write("No functional failures observed.")
                        window_rows = [
                            {
                                "Window": w["index"],
                                "p95 (ms)": w["stats"]["p95_ms"],
                                "ML flagged": w["flagged"],
                                "Note": w["note"],
                                "Model version": w["model_version"],
                            }
                            for w in endpoint["windows"]
                        ]
                        st.dataframe(pd.DataFrame(window_rows), hide_index=True)
                st.download_button(
                    "Download report",
                    json.dumps(result, indent=2),
                    file_name=f"run-{result['id']}.json",
                    mime="application/json",
                )
    else:
        st.info("Run your first release check.")

with tabs[2]:
    st.subheader("Before and after")
    completed = [r for r in history if r["state"] == "COMPLETED"]
    if len(completed) >= 2:
        labels = {r["id"]: r["label"] for r in releases}
        run_by_id = {run["id"]: run for run in completed}
        choices = list(reversed(run_by_id))
        healthy_releases = {r["id"] for r in releases if r["variant"] == "healthy"}
        default_baseline = next(
            (r["id"] for r in completed if r["release_id"] in healthy_releases), choices[0]
        )

        def formatter(run_id):
            return f"#{run_id} · {labels.get(run_by_id[run_id]['release_id'])}"

        left, right = st.columns(2)
        baseline = left.selectbox(
            "Baseline",
            choices,
            index=choices.index(default_baseline),
            format_func=formatter,
            key="baseline_run_id",
        )
        candidate = right.selectbox(
            "Candidate",
            choices,
            index=len(choices) - 1,
            format_func=formatter,
            key="candidate_run_id",
        )
        comparison = request(
            "GET",
            "/comparisons",
            params={
                "baseline_run_id": baseline,
                "candidate_run_id": candidate,
            },
        )
        if comparison:
            st.caption(comparison["comparison_rule"])
            for row in comparison["rows"]:
                st.markdown(f"**{row['endpoint']}** — {', '.join(row['findings'])}")
                left, middle, right = st.columns(3)

                def latency(value):
                    return f"{value:.1f} ms" if value is not None else "No valid responses"

                left.metric("Baseline p95", latency(row["before"]["p95_ms"]))
                middle.metric("Candidate p95", latency(row["after"]["p95_ms"]))
                change = row["p95_change_percent"]
                right.metric("Change", f"{change:+.1f}%" if change is not None else "Unavailable")
                if row["after"]["evidence"]:
                    st.dataframe(pd.DataFrame(row["after"]["evidence"]), hide_index=True)
            st.caption(comparison["limitations"])
    else:
        st.info("Complete at least two runs to compare releases.")

with tabs[3]:
    st.subheader("Measured model performance")
    evaluation = Path(os.getenv("EVALUATION_PATH", "results/evaluation.json"))
    if evaluation.exists():
        summary = json.loads(evaluation.read_text())
        st.caption(summary["scope"])
        st.caption(summary["threshold_policy"])
        rows = []
        for level in ("window_level", "run_level", "raw_window_level", "raw_run_level"):
            if level not in summary:
                continue
            for method, values in summary[level].items():
                rows.append(
                    {
                        "Level": level,
                        "Method": method,
                        **{k: v for k, v in values.items() if k != "confusion_matrix"},
                    }
                )
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.json(summary["affected_endpoint_by_scenario"])
        for limitation in summary["limitations"]:
            st.caption(limitation)
    else:
        st.info("Collect experiments, train models, and evaluate to populate this page.")
        st.code("python -m scripts.experiment\npython -m scripts.train\npython -m scripts.evaluate")
