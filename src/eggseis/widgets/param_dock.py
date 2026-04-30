"""Auto-generated parameter editor for the active plugin."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from eggseis.plugin import Param, PluginSpec


def _widget_options_for(p: Param) -> dict:
    opts: dict = {}
    if p.label:
        opts["label"] = p.label
    if p.units:
        opts["tooltip"] = f"Units: {p.units}"
    if isinstance(p.default, bool):
        if p.choices is not None:
            opts["choices"] = list(p.choices)
        return opts
    if isinstance(p.default, (int, float)):
        if p.min is not None:
            opts["min"] = p.min
        if p.max is not None:
            opts["max"] = p.max
        if p.step is not None:
            opts["step"] = p.step
        elif (
            isinstance(p.default, float)
            and p.min is not None
            and p.max is not None
        ):
            # magicgui FloatSlider defaults step=1.0; derive a smooth one.
            opts["step"] = (float(p.max) - float(p.min)) / 1000.0
    if p.choices is not None:
        opts["choices"] = list(p.choices)
    return opts


def _widget_type_for(p: Param) -> str | None:
    """Pick a slider when a numeric Param has both bounds; else let magicgui decide."""
    if p.choices is not None:
        return None
    if isinstance(p.default, bool):
        return None
    if isinstance(p.default, float) and p.min is not None and p.max is not None:
        return "FloatSlider"
    if isinstance(p.default, int) and p.min is not None and p.max is not None:
        return "Slider"
    return None


class ParamDock(QWidget):
    """Build a magicgui Container from a PluginSpec, emit validated params."""

    paramsChanged = Signal(object)  # emits a pydantic BaseModel

    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._title = QLabel("(no plugin)")
        self._layout.addWidget(self._title)
        self._spec: PluginSpec | None = None
        self._widgets: dict[str, object] = {}
        self._gui: object | None = None

    def current_spec(self) -> PluginSpec | None:
        return self._spec

    def set_plugin(self, spec: PluginSpec | None, params: BaseModel | None = None) -> None:
        self._clear()
        self._spec = spec
        if spec is None:
            self._title.setText("(no plugin)")
            return
        self._title.setText(spec.name)
        if not spec.params_decl:
            # No params — emit defaults for callers that didn't already
            # have them (legacy single-attribute path). When the caller
            # supplied params, they already know the values.
            if params is None:
                self.paramsChanged.emit(spec.param_model())
            return

        from magicgui.widgets import Container, create_widget

        initial = (params if params is not None else spec.param_model()).model_dump()
        widgets: dict[str, object] = {}
        children = []
        for name, p in spec.params_decl.items():
            opts = _widget_options_for(p)
            wt = _widget_type_for(p)
            kwargs = {"value": initial[name], "name": name, "options": opts}
            if wt is not None:
                kwargs["widget_type"] = wt
            w = create_widget(**kwargs)
            w.changed.connect(self._emit)
            widgets[name] = w
            children.append(w)
        container = Container(widgets=children, labels=True)
        self._widgets = widgets
        self._gui = container
        self._layout.addWidget(container.native)
        # Initial emit only when the caller has no params yet. When the
        # caller supplied params (e.g. PipelineDock factory), an emit here
        # would round-trip the same values through pipeline.set_params and
        # trigger a redundant compute request.
        if params is None:
            self._emit()

    def current_params(self) -> BaseModel | None:
        """Return the current params as a pydantic model, or None if no plugin set."""
        spec = self._spec
        if spec is None:
            return None
        if not spec.params_decl:
            return spec.param_model()
        values = {name: w.value for name, w in self._widgets.items()}
        try:
            return spec.param_model(**values)
        except ValidationError:
            return None

    def _emit(self, *_args) -> None:
        params = self.current_params()
        if params is not None:
            self.paramsChanged.emit(params)

    def _clear(self) -> None:
        if self._gui is not None:
            self._layout.removeWidget(self._gui.native)  # type: ignore[attr-defined]
            self._gui.native.deleteLater()  # type: ignore[attr-defined]
        self._gui = None
        self._widgets = {}
