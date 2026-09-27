import type { JsonObject } from "../../shared/JsonTypes";
import type { EditorMapDocument } from "./EditorModels";

export type EditorHistoryActionType =
  | "move_object"
  | "retime_object"
  | "add_object"
  | "delete_object"
  | "reset_object"
  | "reset_map"
  | "batch_metadata_edit"
  | "move_and_retime_object";

export interface EditorHistoryEntryBase {
  sequence: number;
  action: EditorHistoryActionType;
  summary: string;
  timeMs?: number;
}

export interface MoveObjectHistoryEntry extends EditorHistoryEntryBase {
  action: "move_object" | "retime_object" | "move_and_retime_object";
  objectId: string;
  before: JsonObject;
  after: JsonObject;
}

export interface AddDeleteObjectHistoryEntry extends EditorHistoryEntryBase {
  action: "add_object" | "delete_object";
  objectId: string;
  objectSnapshot: JsonObject;
  objectIndex: number;
}

export interface ResetObjectHistoryEntry extends EditorHistoryEntryBase {
  action: "reset_object";
  objectId: string;
  before?: JsonObject;
  after?: JsonObject;
  objectIndex: number;
}

export interface ResetMapHistoryEntry extends EditorHistoryEntryBase {
  action: "reset_map";
  beforeMap: EditorMapDocument;
  afterMap: EditorMapDocument;
}

export interface MetadataHistoryEntry extends EditorHistoryEntryBase {
  action: "batch_metadata_edit";
  before: JsonObject;
  after: JsonObject;
}

export type EditorHistoryEntry =
  | MoveObjectHistoryEntry
  | AddDeleteObjectHistoryEntry
  | ResetObjectHistoryEntry
  | ResetMapHistoryEntry
  | MetadataHistoryEntry;
