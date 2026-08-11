import ast
from pathlib import Path


LAUNCH_FILE = Path(__file__).parents[1] / "launch" / "ai_runtime.launch.py"


def _keyword_string(call, keyword_name):
    keyword = next(item for item in call.keywords if item.arg == keyword_name)
    assert isinstance(keyword.value, ast.Constant)
    return keyword.value.value


def _node_calls(tree):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Node"
    ]


def _node_named(tree, name):
    matches = [
        node
        for node in _node_calls(tree)
        if _keyword_string(node, "name") == name
    ]
    assert len(matches) == 1
    return matches[0]


def _launch_tree():
    return ast.parse(LAUNCH_FILE.read_text(encoding="utf-8"))


def test_python_remains_the_default_primary_planner():
    tree = _launch_tree()
    declarations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DeclareLaunchArgument"
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "planner_implementation"
    ]

    assert len(declarations) == 1
    assert _keyword_string(declarations[0], "default_value") == "python"
    choices = next(
        item.value for item in declarations[0].keywords if item.arg == "choices"
    )
    assert [item.value for item in choices.elts] == ["python", "cpp"]


def test_cpp_shadow_topics_are_hard_isolated():
    shadow = _node_named(_launch_tree(), "vlm_planner_cpp_shadow_node")

    assert _keyword_string(shadow, "package") == "vlm_planner_cpp_pkg"
    assert _keyword_string(shadow, "executable") == "vlm_planner_node"
    condition = next(item.value for item in shadow.keywords if item.arg == "condition")
    condition_source = ast.unparse(condition)
    assert "planner_implementation" in condition_source
    assert "planner_shadow_enabled" in condition_source
    assert "python" in condition_source
    remappings = next(
        item.value for item in shadow.keywords if item.arg == "remappings"
    )
    pairs = {
        tuple(element.value for element in pair.elts) for pair in remappings.elts
    }
    assert pairs == {
        ("/planner/command", "/shadow/planner/command"),
        ("/runtime/events", "/shadow/runtime/events"),
    }


def test_can_bridge_cannot_consume_the_shadow_command_topic():
    can_bridge = _node_named(_launch_tree(), "can_bridge_node")
    source = ast.unparse(can_bridge)

    assert "/shadow/planner/command" not in source
    assert "/planner/command" in source
    assert "/action_manager/command_result" in source
