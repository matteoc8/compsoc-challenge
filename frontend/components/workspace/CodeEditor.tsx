"use client";
// CodeMirror 6: Python highlighting, 4-space indentation, Tab/Shift+Tab, auto-indent after ':',
// smart dedent after return/pass/break/continue/raise and on else/elif/except/finally,
// bracket matching and auto-close, indentation guides, multi-cursor, find/replace,
// Ctrl+/ comment, undo history, autocomplete (keywords, builtins, names in the file),
// and Ruff linting in a Web Worker.

import { indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { indentUnit } from "@codemirror/language";
import { lintGutter } from "@codemirror/lint";
import { EditorState, Prec, type Extension } from "@codemirror/state";
import { EditorView, keymap, type Command } from "@codemirror/view";
import { indentationMarkers } from "@replit/codemirror-indentation-markers";
import { vscodeDark } from "@uiw/codemirror-theme-vscode";
import CodeMirror from "@uiw/react-codemirror";
import { useMemo, useRef } from "react";
import { ruffLinter } from "@/lib/ruff";

const EXIT_LINE = /^([ \t]*)(return\b.*|pass|break|continue|raise\b.*)[ \t]*$/;

// Enter at the end of a `return …` / `pass` / `break` / `continue` / `raise …` line dedents one level.
const newlineAndDedentAfterExit: Command = (view) => {
  const { state } = view;
  const sel = state.selection.main;
  if (!sel.empty || state.selection.ranges.length > 1) return false;
  const line = state.doc.lineAt(sel.head);
  if (sel.head !== line.to) return false;
  const m = EXIT_LINE.exec(line.text);
  if (!m || /[([{,\\]\s*$/.test(line.text)) return false; // a multi-line return continues
  const width = m[1].replace(/\t/g, "    ").length;
  const indent = " ".repeat(Math.max(0, width - 4));
  view.dispatch({
    changes: { from: sel.head, insert: "\n" + indent },
    selection: { anchor: sel.head + 1 + indent.length },
    scrollIntoView: true,
    userEvent: "input",
  });
  return true;
};

const theme = EditorView.theme({
  "&": { fontSize: "15px", height: "100%" },
  ".cm-scroller": { fontFamily: "var(--font-mono), ui-monospace, monospace", lineHeight: "1.55" },
  ".cm-content": { paddingBottom: "40vh" },
  ".cm-tooltip-lint": { fontFamily: "var(--font-mono), monospace", fontSize: "13px" },
});

export function CodeEditor({
  value,
  onChange,
  onRun,
  onSubmit,
  readOnly = false,
  lint = true,
  autoFocus = false,
  minHeight,
  ariaLabel = "Code editor",
}: {
  value: string;
  onChange?: (v: string) => void;
  onRun?: () => void;
  onSubmit?: () => void;
  readOnly?: boolean;
  lint?: boolean;
  autoFocus?: boolean;
  minHeight?: string;
  ariaLabel?: string;
}) {
  // Keep callbacks in refs so the extension list stays stable (no editor rebuilds).
  const runRef = useRef(onRun);
  const submitRef = useRef(onSubmit);
  runRef.current = onRun;
  submitRef.current = onSubmit;

  const extensions = useMemo<Extension[]>(() => {
    const exts: Extension[] = [
      python(),
      indentUnit.of("    "),
      EditorState.tabSize.of(4),
      indentationMarkers({ thickness: 1, colors: { light: "#3a4358", dark: "#3a4358", activeLight: "#6b7690", activeDark: "#6b7690" } }),
      Prec.highest(
        keymap.of([
          { key: "Mod-'", run: () => (runRef.current?.(), true), preventDefault: true },
          { key: "Mod-Enter", run: () => (submitRef.current?.(), true), preventDefault: true },
        ]),
      ),
      Prec.high(keymap.of([{ key: "Enter", run: newlineAndDedentAfterExit }, indentWithTab])),
      theme,
      EditorView.contentAttributes.of({ "aria-label": ariaLabel, spellcheck: "false", autocapitalize: "off", autocorrect: "off" }),
    ];
    if (lint && !readOnly) exts.push(ruffLinter(), lintGutter());
    return exts;
  }, [lint, readOnly, ariaLabel]);

  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      theme={vscodeDark}
      extensions={extensions}
      readOnly={readOnly}
      editable={!readOnly}
      autoFocus={autoFocus}
      height="100%"
      minHeight={minHeight}
      className="h-full"
      basicSetup={{
        lineNumbers: true,
        foldGutter: true,
        highlightActiveLine: !readOnly,
        highlightActiveLineGutter: !readOnly,
        bracketMatching: true,
        closeBrackets: true,
        autocompletion: true,
        history: true,
        searchKeymap: true,
        rectangularSelection: true,
        crosshairCursor: true,
        allowMultipleSelections: true,
        indentOnInput: true,
        tabSize: 4,
        defaultKeymap: true,
        historyKeymap: true,
        foldKeymap: true,
        completionKeymap: true,
        lintKeymap: true,
      }}
    />
  );
}

export default CodeEditor;
