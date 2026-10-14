/**
 * RepoQuill Pi bridge extension (loaded by the Pi runtime via -e).
 *
 * Registers exactly the docs-only, vetted tool allowlist
 * (repoquill/pi/contracts.py DOC_TOOL_ALLOWLIST) as Pi tools. Every
 * execution is delegated over a Unix domain socket (line-oriented JSON
 * envelope, protocol version 1) to the Python PiBridgeServer, which owns
 * all filesystem/execution policy. This extension performs NO local file
 * access and holds NO credentials — it is a thin, stateless proxy.
 *
 * Environment (set by the RepoQuill bootstrap per task):
 *   REPOQUILL_BRIDGE_SOCKET      path of the per-task Unix socket
 *   REPOQUILL_ALLOW_EXAMPLE_EXEC "1"/"true" enables the run_example tool
 *
 * The extension loads cleanly without either variable: tools are still
 * registered and calls fail with a clear error message.
 *
 * Single file, no build step (jiti loads .ts directly). Imports only
 * Node builtins plus `typebox` and the pi package, both of which the Pi
 * runtime resolves for extensions (see its extension loader aliases).
 */

import * as net from "node:net";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const SOCKET_ENV = "REPOQUILL_BRIDGE_SOCKET";
const EXEC_ENV = "REPOQUILL_ALLOW_EXAMPLE_EXEC";
const PROTOCOL_VERSION = 1;
/** Generous client-side deadline; the Python side enforces the real caps. */
const CALL_TIMEOUT_MS = 180_000;

type Envelope = {
	v: number;
	id: string;
	ok: boolean;
	data?: unknown;
	error?: string;
};

type Pending = {
	resolve: (env: Envelope) => void;
	reject: (err: Error) => void;
	timer: ReturnType<typeof setTimeout>;
};

// ---------------------------------------------------------------------------
// Socket client (lazy connect, keep-alive, line framing, partial-read safe)
// ---------------------------------------------------------------------------

let socketPath: string | undefined;
let allowExampleExec = false;

let sock: net.Socket | null = null;
let buffer = "";
let counter = 0;
const pending = new Map<string, Pending>();

function rejectAllPending(err: Error): void {
	for (const [id, p] of pending) {
		pending.delete(id);
		clearTimeout(p.timer);
		p.reject(err);
	}
}

function destroySocket(): void {
	if (sock) {
		const s = sock;
		sock = null;
		try {
			s.destroy();
		} catch {
			// ignore
		}
	}
	buffer = "";
	if (pending.size > 0) {
		rejectAllPending(new Error("RepoQuill bridge connection lost"));
	}
}

function onSocketData(chunk: Buffer): void {
	buffer += chunk.toString("utf8");
	let idx: number;
	while ((idx = buffer.indexOf("\n")) !== -1) {
		const line = buffer.slice(0, idx);
		buffer = buffer.slice(idx + 1);
		if (!line) continue;
		let env: Envelope;
		try {
			env = JSON.parse(line) as Envelope;
		} catch {
			continue; // never let a malformed frame kill the client
		}
		const p = pending.get(env.id);
		if (p) {
			pending.delete(env.id);
			clearTimeout(p.timer);
			p.resolve(env);
		}
	}
}

function openSocket(): Promise<net.Socket> {
	return new Promise<net.Socket>((resolve, reject) => {
		const s = net.createConnection(socketPath as string);
		const fail = (err: Error): void => {
			s.destroy();
			reject(err);
		};
		s.once("error", fail);
		s.once("connect", () => {
			s.removeListener("error", fail);
			s.on("data", onSocketData);
			s.on("error", (err: Error) => {
				destroySocket();
				// already pending calls are rejected by destroySocket
				console.error(`[repoquill-bridge] socket error: ${err.message}`);
			});
			s.on("close", () => destroySocket());
			sock = s;
			buffer = "";
			resolve(s);
		});
	});
}

function callBridge(tool: string, args: Record<string, unknown>): Promise<Envelope> {
	if (!socketPath) {
		return Promise.reject(
			new Error(
				"RepoQuill bridge is not configured (REPOQUILL_BRIDGE_SOCKET is unset)",
			),
		);
	}
	counter += 1;
	const id = `pi-ext-${counter}`;
	const line = JSON.stringify({ v: PROTOCOL_VERSION, id, tool, args }) + "\n";

	return new Promise<Envelope>((resolve, reject) => {
		const timer = setTimeout(() => {
			pending.delete(id);
			reject(new Error(`RepoQuill bridge call to ${tool} timed out`));
		}, CALL_TIMEOUT_MS);
		pending.set(id, { resolve, reject, timer });

		const onSendFailure = (err: Error): void => {
			const p = pending.get(id);
			if (!p) return;
			pending.delete(id);
			clearTimeout(p.timer);
			p.reject(err);
		};

		if (sock && !sock.destroyed) {
			let sent = false;
			try {
				sent = sock.write(line);
			} catch {
				sent = false;
			}
			if (sent) return;
			destroySocket();
		}
		openSocket()
			.then((s) => {
				try {
					s.write(line);
				} catch (err) {
					destroySocket();
					onSendFailure(
						err instanceof Error ? err : new Error(String(err)),
					);
				}
			})
			.catch((err: Error) => {
				onSendFailure(
					new Error(`RepoQuill bridge unreachable: ${err.message}`),
				);
			});
	});
}

// ---------------------------------------------------------------------------
// Tool declarations (parameters mirror repoquill/agents/contracts.py
// TOOL_SCHEMAS; descriptions are model-facing).
// ---------------------------------------------------------------------------

const TOOL_DEFS: {
	name: string;
	label: string;
	description: string;
	parameters: ReturnType<typeof Type.Object>;
}[] = [
	{
		name: "list_files",
		label: "List Files",
		description:
			"List files in the repository (relative paths). Use this to explore the layout before reading specific files.",
		parameters: Type.Object({
			path: Type.Optional(
				Type.String({
					description:
						"Subdirectory relative to the repo root to list. Defaults to the repo root.",
				}),
			),
			pattern: Type.Optional(
				Type.String({
					description: "Optional glob to filter file names, e.g. '*.py'.",
				}),
			),
		}),
	},
	{
		name: "read_file",
		label: "Read File",
		description:
			"Read the contents of a file (read-only). Use it to inspect source, tests, or an existing documentation page.",
		parameters: Type.Object({
			path: Type.String({ description: "Relative path from the repo root." }),
			start_line: Type.Optional(
				Type.Number({ description: "1-based inclusive start line (optional)." }),
			),
			end_line: Type.Optional(
				Type.Number({ description: "1-based inclusive end line (optional)." }),
			),
		}),
	},
	{
		name: "search_code",
		label: "Search Code",
		description:
			"Search file contents for a literal or regex pattern. Returns matching lines as 'relpath:line: text'. Use it to find where a symbol is defined or how it is used.",
		parameters: Type.Object({
			pattern: Type.String({
				description: "Literal string or regex to search for.",
			}),
			path: Type.Optional(
				Type.String({
					description:
						"Restrict the search to a subdirectory (relative). Defaults to the repo root.",
				}),
			),
			regex: Type.Optional(
				Type.Boolean({ description: "Treat pattern as a regex. Default false." }),
			),
			max_results: Type.Optional(
				Type.Number({ description: "Cap on the number of results." }),
			),
		}),
	},
	{
		name: "inspect_api",
		label: "Inspect API",
		description:
			"Return the AST-extracted public API surface of the package (or a single module): classes, functions, methods, properties and signatures. This is the authoritative list of symbols that actually exist — do not document anything that is not here.",
		parameters: Type.Object({
			module: Type.Optional(
				Type.String({
					description:
						"Restrict to one module (dot-separated). Defaults to the whole package.",
				}),
			),
			symbol: Type.Optional(
				Type.String({
					description: "Focus on one class or function name.",
				}),
			),
		}),
	},
	{
		name: "inspect_tests",
		label: "Inspect Tests",
		description:
			"Discover the repository's test files and return their paths plus optional excerpts. Tests are behavioral ground truth: if a test asserts something, the docs may state it.",
		parameters: Type.Object({
			module: Type.Optional(
				Type.String({
					description: "Restrict to tests of one module (optional).",
				}),
			),
			max_chars: Type.Optional(
				Type.Number({
					description: "Cap on the amount of returned text.",
				}),
			),
		}),
	},
	{
		name: "run_example",
		label: "Run Example",
		description:
			"Execute a Python snippet in an isolated, credential-free subprocess with a wall-clock timeout. Use it to verify that a code example actually works BEFORE you document it. Never use it for anything other than documentation examples.",
		parameters: Type.Object({
			code: Type.String({ description: "The Python code to execute." }),
			timeout: Type.Optional(
				Type.Number({
					description:
						"Wall-clock seconds. Defaults to the context value.",
				}),
			),
		}),
	},
	{
		name: "write_doc",
		label: "Write Doc",
		description:
			"Write (create or overwrite) the documentation page for this task. This is the ONLY file you may write. Provide the complete markdown page. Call this once you are finished, then stop calling tools.",
		parameters: Type.Object({
			slug: Type.String({
				description:
					"Page slug (kebab-case, no .md extension). Must be the slug of this task.",
			}),
			content: Type.String({
				description: "The complete markdown page content.",
			}),
		}),
	},
];

// ---------------------------------------------------------------------------
// Extension entry point
// ---------------------------------------------------------------------------

export default function repoquillBridgeExtension(pi: ExtensionAPI): void {
	socketPath =
		process.env[SOCKET_ENV] && process.env[SOCKET_ENV].trim()
			? process.env[SOCKET_ENV].trim()
			: undefined;
	const rawExec = (process.env[EXEC_ENV] ?? "").trim().toLowerCase();
	allowExampleExec = rawExec === "1" || rawExec === "true" || rawExec === "yes";

	for (const def of TOOL_DEFS) {
		if (def.name === "run_example" && !allowExampleExec) continue;
		pi.registerTool({
			name: def.name,
			label: def.label,
			description: def.description,
			parameters: def.parameters,
			async execute(_toolCallId: string, params: unknown) {
				const args = (
					params && typeof params === "object" ? params : {}
				) as Record<string, unknown>;
				try {
					const env = await callBridge(def.name, args);
					if (env.ok) {
						return {
							content: [
								{
									type: "text" as const,
									text: JSON.stringify(env.data ?? null),
								},
							],
							details: { ok: true },
						};
					}
					const msg =
						typeof env.error === "string"
							? env.error
							: "unknown bridge error";
					return {
						content: [{ type: "text" as const, text: `error: ${msg}` }],
						details: { ok: false },
						isError: true,
					};
				} catch (err) {
					const msg = err instanceof Error ? err.message : String(err);
					return {
						content: [{ type: "text" as const, text: `error: ${msg}` }],
						details: { ok: false },
						isError: true,
					};
				}
			},
		});
	}
}
