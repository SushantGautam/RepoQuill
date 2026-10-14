// Probe extension for the REAL pi binary (no bridge, local file ops only).
// Used by the security test to prove that under SAFE_LAUNCH_FLAGS the only
// executable tools are the ones registered here — no builtin bash/write/
// edit is active. Root is process.cwd() (the backend sets it to the task
// source root); staged writes go to REPOQUILL_FAKE_STAGED_DIR.
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const staged =
	process.env.REPOQUILL_FAKE_STAGED_DIR
		? path.resolve(process.env.REPOQUILL_FAKE_STAGED_DIR)
		: path.join(process.cwd(), "staged");

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "list_files",
		description: "List files under the working directory.",
		parameters: Type.Object({
			path: Type.Optional(Type.String()),
		}),
		async execute(_id, params) {
			const base = params.path ? path.join(process.cwd(), params.path) : process.cwd();
			const files: string[] = [];
			const walk = (dir: string) => {
				if (!existsSync(dir)) return;
				for (const e of readdirSync(dir)) {
					const full = path.join(dir, e);
					const rel = path.relative(process.cwd(), full).split(path.sep).join("/");
					if (statSync(full).isDirectory()) walk(full);
					else files.push(rel);
				}
			};
			walk(base);
			return { content: [{ type: "text", text: JSON.stringify({ files }) }], details: {} };
		},
	});

	pi.registerTool({
		name: "read_file",
		description: "Read a file under the working directory.",
		parameters: Type.Object({ path: Type.String() }),
		async execute(_id, params) {
			return {
				content: [{ type: "text", text: readFileSync(path.join(process.cwd(), params.path), "utf8") }],
				details: { path: params.path },
			};
		},
	});

	pi.registerTool({
		name: "inspect_api",
		description: "Inspect the package API surface.",
		parameters: Type.Object({ symbol: Type.Optional(Type.String()) }),
		async execute(_id, params) {
			return {
				content: [{ type: "text", text: `API surface for ${params.symbol ?? "(package)"}` }],
				details: { symbol: params.symbol },
			};
		},
	});

	pi.registerTool({
		name: "write_doc",
		description: "Write one documentation page into the staging tree.",
		parameters: Type.Object({
			slug: Type.String(),
			content: Type.String(),
		}),
		async execute(_id, params) {
			mkdirSync(staged, { recursive: true });
			const out = path.join(staged, params.slug + ".md");
			writeFileSync(out, params.content, "utf8");
			return {
				content: [{ type: "text", text: JSON.stringify({ slug: params.slug, path: out }) }],
				details: { slug: params.slug },
			};
		},
	});
}
