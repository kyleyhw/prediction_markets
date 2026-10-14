// Runs a visitor's strategy code (pages/strategy_api.py) with Pyodide, Python
// compiled to WebAssembly, off the page's thread, so a slow or endless loop
// cannot freeze the page: the page stops this worker after a time limit.
importScripts('https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.js');

let ready = null;

onmessage = async (e) => {
  const { code, api, data, cutoff } = e.data;
  const printed = [];
  try {
    ready = ready || loadPyodide();
    const py = await ready;
    py.setStdout({ batched: (s) => { if (printed.length < 200) printed.push(s); } });
    py.setStderr({ batched: (s) => { if (printed.length < 200) printed.push(s); } });
    py.globals.set('api_source', api);
    py.globals.set('user_code', code);
    py.globals.set('data_json', JSON.stringify(data));
    py.globals.set('cutoff', cutoff);
    const out = await py.runPythonAsync(`
import json, sys, types
api = types.ModuleType("strategy_api")
sys.modules["strategy_api"] = api  # before running it: dataclasses look it up
exec(compile(api_source, "strategy_api.py", "exec"), api.__dict__)
namespace = {"__name__": "your_strategy"}
exec(compile(user_code, "your_strategy.py", "exec"), namespace)
json.dumps(api.run(namespace, json.loads(data_json), cutoff))
`);
    postMessage({ ok: true, result: JSON.parse(out), printed });
  } catch (err) {
    // The last lines of a Python traceback say what went wrong and where.
    const text = String(err && err.message ? err.message : err);
    // Only the lines in the visitor's own code, then the error itself.
    const lines = text.trim().split('\n');
    const where = [];
    lines.forEach((l, i) => { if (l.includes('"your_strategy.py"')) where.push(l.trim(), (lines[i + 1] || '').trim()); });
    postMessage({ ok: false, error: [...new Set([...where, lines[lines.length - 1]])].filter(Boolean).join('\n'), printed });
  }
};
