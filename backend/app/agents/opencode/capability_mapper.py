"""Shared runtime capability mapping for the OpenCode adapters.

Pure functions only: raw provider dictionaries go in, provider-neutral domain
models come out. Provider-native structures never leave adapter-private code,
unknown fields are ignored safely, and nothing is ever invented - a missing
input simply produces an unavailable section with an exact reason.

Two shapes are mapped:

- ACP v1: ``configOptions`` descriptors (categories ``model`` /
  ``thought_level`` / ``mode``), legacy session-mode state, and
  ``available_commands_update`` payloads.
- OpenCode Server HTTP API: ``/config/providers``, selected model from
  ``/config``, and ``/command`` listings.
"""

from __future__ import annotations

from typing import Any

from ..capabilities import (
    CapabilitySection,
    CommandDescriptor,
    ModeDescriptor,
    ModelDescriptor,
    ThinkingOption,
    UnavailabilityReason,
    UnavailableCapability,
)

# Reserved ACP config-option categories (integration constants, not data).
CATEGORY_MODEL = "model"
CATEGORY_THOUGHT_LEVEL = "thought_level"
CATEGORY_MODE = "mode"


def _unavailable(reason: UnavailabilityReason, message: str) -> UnavailableCapability:
    return UnavailableCapability(reason=reason, message=message)


def _select_option(
    config_option: dict[str, Any],
) -> tuple[
    list[ModelDescriptor] | None,
    list[ThinkingOption] | None,
    list[ModeDescriptor] | None,
    str | None,
]:
    """Map one select-type config option into its typed slice, if recognized.

    Returns (models, thinking, modes, current_value). Unrecognized categories
    yield (None, None, None, None) and are ignored upstream.
    """
    if config_option.get("type") != "select":
        return None, None, None, None
    category = config_option.get("category")
    entries: list[ModelDescriptor | ThinkingOption | ModeDescriptor] = []
    for entry in config_option.get("options") or []:
        descriptor = _value_to_descriptor(category, entry)
        if descriptor is not None:
            entries.append(descriptor)
    current = config_option.get("currentValue")
    if not isinstance(current, str):
        current = None
    if category == CATEGORY_MODEL and entries:
        models = [e for e in entries if isinstance(e, ModelDescriptor)]
        return models, None, None, current
    if category == CATEGORY_THOUGHT_LEVEL and entries:
        thinking = [e for e in entries if isinstance(e, ThinkingOption)]
        return None, thinking, None, current
    if category == CATEGORY_MODE and entries:
        modes = [e for e in entries if isinstance(e, ModeDescriptor)]
        return None, None, modes, current
    return None, None, None, None


def _value_to_descriptor(
    category: str | None, entry: Any
) -> ModelDescriptor | ThinkingOption | ModeDescriptor | None:
    """Convert one {value,name,description} entry; ids stay runtime-supplied."""
    if not isinstance(entry, dict):
        return None
    value = entry.get("value")
    name = entry.get("name")
    if not isinstance(value, str) or not isinstance(name, str):
        return None
    description = entry.get("description") or ""
    label = name if isinstance(name, str) else value
    if category == CATEGORY_MODEL:
        return ModelDescriptor(id=value, label=label)
    if category == CATEGORY_THOUGHT_LEVEL:
        return ThinkingOption(id=value, label=label)
    if category == CATEGORY_MODE:
        return ModeDescriptor(id=value, label=label, description=str(description))
    return None


class AcpCapabilityState:
    """Authoritative capability state assembled from live ACP traffic."""

    def __init__(self) -> None:
        self.models: CapabilitySection[ModelDescriptor] = CapabilitySection()
        self.thinking: CapabilitySection[ThinkingOption] = CapabilitySection()
        self.modes: CapabilitySection[ModeDescriptor] = CapabilitySection()
        self.commands: CapabilitySection[CommandDescriptor] = CapabilitySection()
        self.selected_model: str | None = None
        self.selected_mode: str | None = None
        self.selected_thinking: str | None = None
        self.selected_agent: str | None = None
        self.model_config_id: str | None = None
        self.mode_config_id: str | None = None
        self.thought_level_config_id: str | None = None
        # Attachment capabilities mapped from ACP InitializeResponse.
        self.attachment_resource_links: bool = True  # baseline per ACP v1
        self.attachment_images: bool = False
        self.attachment_audio: bool = False
        self.attachment_embedded: bool = False

    # -- ingest ------------------------------------------------------------

    def ingest_session_state(self, result: Any) -> None:
        """Fold new-session / resume results: configOptions plus legacy modes.

        Some SDK response models dump to a bare session-id string when the
        result carries nothing but the id - nothing to map in that case.
        """
        if not isinstance(result, dict):
            return
        options = result.get("configOptions")
        if isinstance(options, list):
            self.ingest_config_options(options)
        legacy = result.get("modes")
        if isinstance(legacy, dict) and not self._mode_section_available():
            self._ingest_legacy_modes(legacy)

    def ingest_prompt_capabilities(self, init_response: Any) -> None:
        """Map ACP InitializeResponse.agent_capabilities into attachment flags.

        Called after the initialize handshake so the session can check
        capabilities before dispatching prompts with attachments.
        """
        if not isinstance(init_response, dict):
            return
        caps = init_response.get("agentCapabilities")
        if not isinstance(caps, dict):
            return
        pc = caps.get("promptCapabilities")
        if not isinstance(pc, dict):
            return
        self.attachment_images = bool(pc.get("image"))
        self.attachment_audio = bool(pc.get("audio"))
        self.attachment_embedded = bool(pc.get("embeddedContext") or pc.get("embedded_context"))
        # resource_links are baseline per ACP v1 — always True unless
        # the provider explicitly disables them (which compliant agents won't).
        self.attachment_resource_links = True

    def ingest_config_options(self, options: list[Any]) -> None:
        """Replace affected sections from a complete config-options payload.

        A full echo always arrives after set_config_option and inside
        config_option_update notifications, so selection changes refresh every
        dependent slice - notably thought_level after a model change.
        """
        models: list[ModelDescriptor] = []
        thinking: list[ThinkingOption] = []
        modes: list[ModeDescriptor] = []
        for option in options:
            if not isinstance(option, dict):
                continue
            option_id = option.get("id")
            new_models, new_thinking, new_modes, current = _select_option(option)
            if new_models is not None:
                models = new_models
                self.model_config_id = option_id if isinstance(option_id, str) else None
                if current is not None:
                    self.selected_model = current
            elif new_thinking is not None:
                thinking = new_thinking
                self.thought_level_config_id = option_id if isinstance(option_id, str) else None
                if current is not None:
                    self.selected_thinking = current
            elif new_modes is not None:
                modes = new_modes
                self.mode_config_id = option_id if isinstance(option_id, str) else None
                if current is not None:
                    self.selected_mode = current
            # Unknown categories are ignored safely.
        if models:
            self.models = CapabilitySection(items=tuple(models))
        if thinking:
            # Thought-level choices are scoped to the currently selected model.
            self.thinking = CapabilitySection(
                items=tuple(
                    ThinkingOption(id=o.id, label=o.label, model_id=self.selected_model or "")
                    for o in thinking
                )
            )
        if modes:
            self.modes = CapabilitySection(items=tuple(modes))

    def _mode_section_available(self) -> bool:
        return self.modes.available

    def _ingest_legacy_modes(self, state: dict[str, Any]) -> None:
        """Legacy fallback: only when config options did not provide modes."""
        available = state.get("availableModes")
        current = state.get("currentModeId")
        modes = [
            ModeDescriptor(
                id=e["id"],
                label=e["name"] if isinstance(e.get("name"), str) else e["id"],
            )
            for e in available or []
            if isinstance(e, dict) and isinstance(e.get("id"), str)
        ]
        if modes:
            self.modes = CapabilitySection(items=tuple(modes))
            if isinstance(current, str):
                self.selected_mode = current

    def ingest_current_mode_update(self, mode_id: str) -> None:
        if isinstance(mode_id, str):
            self.selected_mode = mode_id

    def ingest_commands(self, commands: list[Any]) -> None:
        parsed = [
            CommandDescriptor(
                name=c["name"],
                description=str(c.get("description", "")),
                input_hint=str((c.get("input") or {}).get("hint", "")),
            )
            for c in commands or []
            if isinstance(c, dict) and isinstance(c.get("name"), str)
        ]
        self.commands = CapabilitySection(items=tuple(parsed))

    # -- projection ---------------------------------------------------------

    def apply_selection_locally(self, kind: str, value: str) -> None:
        """Provisional pre-ack view; authoritative echoes replace it later."""
        if kind == "model":
            self.selected_model = value
        elif kind == "mode":
            self.selected_mode = value
        elif kind == "thinking":
            self.selected_thinking = value
        elif kind == "agent":
            self.selected_agent = value


def command_item(command: Any) -> dict[str, str]:
    """Map a CommandDescriptor to a Protocol v1 command item.

    Shared by both adapters so the wire shape cannot drift between them.
    """
    item: dict[str, str] = {"id": command.name, "label": command.name}
    if getattr(command, "description", ""):
        item["description"] = command.description
    if getattr(command, "input_hint", ""):
        item["input_hint"] = command.input_hint
    return item


def normalise_providers(providers_payload: Any) -> dict[Any, Any]:
    """Normalise a /config/providers payload into {providerId: provider}.

    `opencode serve` actually returns::

        {"providers": [{"id": "opencode", "name": "OpenCode Zen",
                        "models": {...}}, ...]}

    i.e. the mapping is wrapped in a ``providers`` key AND the value is a list
    of provider objects keyed by their ``id`` field - not a dict keyed by
    provider id. Treating that payload as a provider mapping silently yields
    zero models, which is why models (and thinking, which derives from the
    selected model) came back unavailable.

    Older/documented shapes are still accepted so this stays forward
    compatible: a bare ``{providerId: provider}`` mapping, or a bare list of
    provider objects.
    """
    providers: dict[Any, Any] = {}

    def absorb(entry: Any) -> None:
        if not isinstance(entry, dict):
            return
        key = entry.get("id") or entry.get("name")
        if isinstance(key, str) and key:
            providers[key] = entry

    if isinstance(providers_payload, dict):
        inner = providers_payload.get("providers")
        if isinstance(inner, list):
            for entry in inner:
                absorb(entry)
        elif isinstance(inner, dict):
            providers.update(inner)
        else:
            # Already a providerId -> provider mapping.
            for key, value in providers_payload.items():
                if key == "providers":
                    continue
                providers[key] = value
    elif isinstance(providers_payload, list):
        for entry in providers_payload:
            absorb(entry)
    return providers


def server_models_from_providers(providers_payload: Any) -> list[ModelDescriptor]:
    """Flatten /config/providers into model descriptors (provider/model ids).

    Accepts every shape ``normalise_providers`` understands. Only what the
    server actually reports becomes a descriptor.
    """
    models: list[ModelDescriptor] = []
    for provider_id, provider in normalise_providers(providers_payload).items():
        if not isinstance(provider, dict):
            continue
        container = provider.get("models", {})
        if isinstance(container, dict):
            model_entries = list(container.items())
        elif isinstance(container, list):
            model_entries = [
                (m["id"], m)
                for m in container
                if isinstance(m, dict) and isinstance(m.get("id"), str)
            ]
        else:
            continue
        for model_key, model in model_entries:
            model_id = f"{provider_id}/{model_key}"
            label = model.get("name") if isinstance(model, dict) else None
            models.append(ModelDescriptor(id=model_id, label=label or model_id))
    return models


def server_selected_model(config_payload: Any) -> str | None:
    """Selected model from GET /config (`model` field), when present."""
    if isinstance(config_payload, dict):
        model = config_payload.get("model")
        if isinstance(model, str):
            return model
        if isinstance(model, dict):
            provider = model.get("providerID")
            id_ = model.get("modelID")
            if isinstance(provider, str) and isinstance(id_, str):
                return f"{provider}/{id_}"
    return None
