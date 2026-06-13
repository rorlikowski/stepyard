import pytest

from stepyard.core.expressions import evaluate_expression, resolve_variables
from stepyard.core.flow import Flow


def test_flow_validation_success():
    yaml_content = """
    name: docker-health
    trigger:
      uses: cron
      with:
        schedule: "daily at 08:00"
    steps:
      - id: containers
        uses: docker.containers
      - id: stats
        uses: docker.stats
        with:
          target: ${{ steps.containers.output }}
        if: ${{ steps.containers.output.has_unhealthy }}
    """
    flow = Flow.from_yaml(yaml_content)
    assert flow.model.name == "docker-health"
    assert len(flow.model.steps) == 2
    assert flow.model.steps[0].id == "containers"
    assert flow.model.steps[1].with_config["target"] == "${{ steps.containers.output }}"
    assert flow.model.steps[1].if_cond == "${{ steps.containers.output.has_unhealthy }}"


def test_flow_step_next_and_max_visits():
    yaml_content = """
    name: graph-flow
    steps:
      - id: decide
        uses: flow.route
        max_visits: 3
        next: ${{ steps.decide.output.target }}
        with:
          target: finish
      - id: finish
        uses: shell.run
    """
    flow = Flow.from_yaml(yaml_content)

    assert flow.model.steps[0].next_step == "${{ steps.decide.output.target }}"
    assert flow.model.steps[0].max_visits == 3


def test_flow_validation_fails():
    # Duplicate step IDs
    yaml_content = """
    name: bad-flow
    steps:
      - id: step1
        uses: shell.run
      - id: step1
        uses: http.request
    """
    with pytest.raises(ValueError, match="Step IDs must be unique"):
        Flow.from_yaml(yaml_content)


def test_safe_evaluation_basic():
    context = {"steps": {"containers": {"output": {"has_unhealthy": True, "count": 5}}}}
    # Resolve exact boolean expression
    res = evaluate_expression("steps.containers.output.has_unhealthy", context)
    assert res is True

    # Comparison
    res = evaluate_expression("steps.containers.output.count > 3", context)
    assert res is True

    res = evaluate_expression("steps.containers.output.count == 5", context)
    assert res is True

    # Boolean logic
    res = evaluate_expression(
        "steps.containers.output.count > 2 and steps.containers.output.has_unhealthy", context
    )
    assert res is True


def test_safe_evaluation_security():
    # Attempting to call functions or import packages must raise a TypeError
    context = {}
    with pytest.raises(ValueError):
        evaluate_expression("importos", context)

    with pytest.raises(ValueError):
        # We don't allow call nodes
        evaluate_expression("__import__('os').system('ls')", context)


def test_resolve_variables():
    context = {"steps": {"step1": {"output": {"url": "https://api.example.com", "code": 200}}}}
    config = {
        "endpoint": "${{ steps.step1.output.url }}",
        "description": "Returned status was ${{ steps.step1.output.code }} for api call",
        "nested": {"val": "${{ steps.step1.output.code == 200 }}"},
    }
    resolved = resolve_variables(config, context)
    assert resolved["endpoint"] == "https://api.example.com"
    assert resolved["description"] == "Returned status was 200 for api call"
    assert resolved["nested"]["val"] is True
