// Shared fixture builder for the schema-driven frontend contract suites
// (patients.contract.test.ts #624/#652, consent api.contract.test.ts #648/#661).
//
// Each suite walks the backend's published OpenAPI slice instead of
// hand-copying wire bodies, so a backend rename or added field lands here as a
// failing fixture rather than as drift a page discovers in the browser. The
// walker is one implementation shared by both suites so their build semantics
// cannot drift apart.

export interface OpenApiNode {
  $ref?: string;
  anyOf?: OpenApiNode[];
  enum?: string[];
  properties?: Record<string, OpenApiNode>;
  required?: string[];
  items?: OpenApiNode;
  type?: string;
}

const REF_PREFIX = "#/components/schemas/";

/**
 * Build a body the backend would genuinely send, by walking the schema.
 *
 * Pydantic serialises every declared field, default included, so walking
 * `properties` yields the full wire shape rather than just the required subset.
 * `over` names the handful of values a case wants to assert on; everything else
 * takes the schema's first legal value.
 */
export function makeSliceBody(
  schemas: Record<string, OpenApiNode>,
): (name: string, over?: Record<string, unknown>) => Record<string, unknown> {
  function resolveRef(ref: string): OpenApiNode {
    const name = ref.slice(REF_PREFIX.length);
    const found = schemas[name];
    if (found === undefined) {
      throw new Error(
        `${name} is not in the exported OpenAPI slice; re-run the exporter`,
      );
    }
    return found;
  }

  function build(
    node: OpenApiNode,
    over: Record<string, unknown> = {},
  ): unknown {
    if (node.$ref !== undefined) return build(resolveRef(node.$ref), over);
    if (node.anyOf !== undefined) {
      // Prefer a concrete branch: `X | None` must not collapse the field to null.
      const solid = node.anyOf.filter((branch) => branch.type !== "null");
      return build(solid[0] ?? node.anyOf[0], over);
    }
    if (node.enum !== undefined) return node.enum[0];
    if (node.type === "object") {
      const shape: Record<string, unknown> = {};
      for (const [key, property] of Object.entries(node.properties ?? {})) {
        shape[key] = key in over ? over[key] : build(property);
      }
      return shape;
    }
    // No `over` for element nodes: an override names a field of THIS body, and
    // passing it down would let a parent field name collide with a nested one.
    if (node.type === "array") return [build(node.items ?? {})];
    if (node.type === "boolean") return true;
    if (node.type === "integer" || node.type === "number") return 1;
    if (node.type === "string") return "value";
    return null;
  }

  return (name, over = {}) =>
    build(schemas[name], over) as Record<string, unknown>;
}
