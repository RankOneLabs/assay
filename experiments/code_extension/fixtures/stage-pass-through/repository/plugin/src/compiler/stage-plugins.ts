import type { StageTypeCompilerRegistry } from "./compile-workflow";

export const configureStagePlugins = (
  names: readonly string[],
  available: StageTypeCompilerRegistry,
): StageTypeCompilerRegistry => Object.fromEntries(
  names.filter((name) => available[name] !== undefined).map((name) => [name, available[name]]),
);
