from agent.workspaces import (
    bind_workspace,
    handle_workspace_message,
    load_projects,
    resolve_bound_cwd,
)


def test_existing_context_switch_persists_binding(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    (project / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))

    result = handle_workspace_message(
        f"cd {project}",
        session_id="sid1",
        platform="telegram",
        chat_id="chat1",
        thread_id="",
    )

    assert result.handled
    assert result.persistent
    assert result.cwd == str(project.resolve())
    assert "Workspace switched." in result.message
    assert "Context: AGENTS.md loaded" in result.message
    data = load_projects()
    assert data["workspaces"][str(project.resolve())]["name"] == "repo"
    assert data["bindings"]["sessions"]["sid1"]["cwd"] == str(project.resolve())
    assert data["bindings"]["chats"]["telegram:chat1:"]["cwd"] == str(project.resolve())
    assert resolve_bound_cwd(session_id="sid1") == str(project.resolve())


def test_named_new_workspace_creates_agents_md_without_absolute_cwd(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "new-app"
    monkeypatch.setenv("HERMES_HOME", str(home))

    result = handle_workspace_message(f"cd {project} #NewApp", session_id="sid2")

    assert result.handled
    assert result.persistent
    assert project.is_dir()
    agents = project / "AGENTS.md"
    assert agents.is_file()
    content = agents.read_text(encoding="utf-8")
    assert "project_name: NewApp" in content
    assert str(project.resolve()) not in content
    assert "Workspace initialized." in result.message
    assert load_projects()["workspaces"][str(project.resolve())]["name"] == "NewApp"


def test_directory_without_context_is_transient(tmp_path, monkeypatch):
    home = tmp_path / "home"
    directory = tmp_path / "plain"
    directory.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    result = handle_workspace_message(f"cd {directory}", session_id="sid3")

    assert result.handled
    assert not result.persistent
    assert result.cwd == str(directory.resolve())
    assert "Persistent workspace binding: not updated" in result.message
    assert load_projects()["workspaces"] == {}


def test_name_based_switch_handles_missing_and_match(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "named"
    project.mkdir()
    (project / "AGENTS.md").write_text("# Named\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    handle_workspace_message(f"cd {project} #NewApp", session_id="old")

    missing = handle_workspace_message("switch to Other project", session_id="sid4")
    assert missing.handled
    assert "No workspace named Other was found" in missing.message

    switched = handle_workspace_message("切换到 NewApp 项目", session_id="sid4")
    assert switched.handled
    assert switched.cwd == str(project.resolve())
    assert "Workspace switched." in switched.message
    assert resolve_bound_cwd(session_id="sid4") == str(project.resolve())


def test_workspace_can_be_bound_to_session_after_chat_first_switch(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "chat-first"
    project.mkdir()
    (project / "AGENTS.md").write_text("# Chat first\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))

    switched = handle_workspace_message(
        f"cd {project} #ChatFirst",
        platform="telegram",
        chat_id="chat1",
        thread_id="",
    )

    assert switched.persistent
    assert resolve_bound_cwd(session_id="created-after-switch") == ""
    bind_workspace(
        switched.cwd,
        name=switched.name,
        context_file=switched.context_file,
        session_id="created-after-switch",
        platform="telegram",
        chat_id="chat1",
        thread_id="",
    )
    assert resolve_bound_cwd(session_id="created-after-switch") == str(project.resolve())
