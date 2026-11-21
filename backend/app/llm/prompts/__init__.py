"""Prompt templates, one Markdown file per prompt (CLAUDE.md section 15).

Prompts live in files so they can be reviewed and diffed on their own, without
reading Python. Placeholders use ``string.Template`` syntax (``$name``).
Substitution only processes the template: values (which may be untrusted
document content) are inserted literally and never re-interpreted.

Available prompts:

* ``system``: shared system prompt with the security rules (section 7).
* ``visual_page``: stage-2 instructions for one page image.
* ``visual_guidance_general`` / ``visual_guidance_incident``: profile-specific
  photo guidance inserted into ``visual_page``. The incident one is the
  evidence-observer variant.
* ``document_analysis``: stage-3 analysis of one document (full text or notes).
* ``chunk_notes``: map step for long documents (page-cited notes per group of pages).
* ``consolidation``: stage-4 comparison across documents labelled D1, D2...
* ``retry_invalid_output``: appended to a prompt after a validation failure.
"""

from functools import cache
from importlib.resources import files
from string import Template


@cache
def load_prompt(name: str) -> str:
    """Return the raw text of ``<name>.md`` (cached after the first read).

    Raises:
        FileNotFoundError: No prompt file with that name exists.
    """
    return files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")


def render_prompt(name: str, **values: object) -> str:
    """Load a prompt and substitute ``$placeholders``.

    Raises:
        KeyError: A placeholder in the template has no value. Failing loudly
            beats silently sending a prompt with ``$name`` left in it.
    """
    return Template(load_prompt(name)).substitute({k: str(v) for k, v in values.items()})
