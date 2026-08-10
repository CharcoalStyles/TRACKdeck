import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import Card from "../components/Card";
import Toggle from "../components/Toggle";
import ChatWidget from "../components/chat/ChatWidget";
import ObsidianMarkdown from "../components/vault/ObsidianMarkdown";

export default function ProjectPage() {
  const { name = "" } = useParams<{ name: string }>();
  const projectName = decodeURIComponent(name);
  const threadId = `project_${projectName}`;
  const queryClient = useQueryClient();

  const [agentRun, setAgentRun] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  // First poll deliberately delayed rather than fired the instant polling
  // is enabled — POST /text runs the whole agent turn synchronously
  // server-side, so an immediate poll can race ahead of _run_graph_streamed
  // even registering the thread as running, see it as "not found" (the
  // same {steps: [], done: true} shape as "already finished"), and
  // conclude the run is done before it's begun. Matches the original
  // vanilla implementation's setInterval, whose first tick likewise only
  // fires after the full interval, not at t=0.
  const [pollReady, setPollReady] = useState(false);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  useEffect(() => () => clearTimeout(pollTimeoutRef.current), []);

  const projectQuery = useQuery({
    queryKey: ["project", projectName],
    queryFn: async () => {
      const { data: notesData } = await api.GET("/vault/notes");
      const projectNotes = (notesData?.notes ?? []).filter(
        (n) => n.project === projectName,
      );
      const fullNotes = await Promise.all(
        projectNotes.map(async (n) => {
          const { data } = await api.GET("/vault/notes/{note_id}", {
            params: { path: { note_id: n.id } },
          });
          return data!;
        }),
      );
      const { data: attachmentsData } = await api.GET(
        "/vault/projects/{project}/attachments",
        {
          params: { path: { project: projectName } },
        },
      );
      return {
        notes: fullNotes,
        attachments: attachmentsData?.attachments ?? [],
      };
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file, file.name);
      const { error } = await api.POST(
        "/vault/projects/{project}/attachments",
        {
          params: { path: { project: projectName } },
          body: formData as never,
        },
      );
      if (error) throw new Error("Failed to upload image");
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project", projectName] }),
  });

  const activityQuery = useQuery({
    queryKey: ["agent-activity", threadId],
    queryFn: async () => {
      const { data } = await api.GET("/agent-activity/{thread_id}", {
        params: { path: { thread_id: threadId } },
      });
      return data;
    },
    enabled: isPolling && pollReady,
    refetchInterval: (query) => (query.state.data?.done ? false : 1200),
  });

  const notes = projectQuery.data?.notes ?? [];
  const attachments = projectQuery.data?.attachments ?? [];

  const titleToId = useMemo(
    () => new Map(notes.map((n) => [n.title.trim().toLowerCase(), n.id])),
    [notes],
  );
  const filenameToUrl = useMemo(
    () => new Map(attachments.map((a) => [a.filename, a.url])),
    [attachments],
  );
  const resolveWikilink = (title: string) =>
    titleToId.get(title.trim().toLowerCase()) ?? null;
  const resolveImage = (filename: string) =>
    filenameToUrl.get(filename) ?? null;

  function scrollToNote(noteId: string) {
    document
      .getElementById(`note-${noteId}`)
      ?.scrollIntoView({ behavior: "smooth" });
  }

  const overview = notes.find(
    (n) => n.title.trim().toLowerCase() === projectName.trim().toLowerCase(),
  );
  const rest = notes
    .filter((n) => n !== overview)
    .sort((a, b) => b.updated.localeCompare(a.updated));
  const orderedNotes = [overview, ...rest].filter(
    (n): n is NonNullable<typeof n> => !!n,
  );

  return (
    <Card>
      <Link
        to="/projects"
        className="mb-3 inline-block text-sm text-accent hover:underline">
        ← Back to Projects
      </Link>
      <h2 className="mb-4 text-lg font-semibold">{projectName}</h2>

      {projectQuery.isPending ? (
        <p className="text-sm text-text-muted">Loading...</p>
      ) : notes.length === 0 ? (
        <p className="text-sm text-text-muted">
          No project found with this name.
        </p>
      ) : (
        <>
          {orderedNotes.map((note) => (
            <div key={note.id} className="mb-6">
              <h3
                id={`note-${note.id}`}
                className="mb-2 text-accent-bright font-semibold">
                {note.title}
              </h3>
              <div className="prose-note text-sm leading-relaxed text-text-primary [&_h1]:mt-3 [&_h1]:text-accent-bright [&_h1]:font-semibold [&_h2]:mt-3 [&_h2]:text-accent-bright [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:text-sm [&_h3]:font-semibold [&_img]:my-2 [&_img]:max-w-full [&_img]:rounded [&_li]:ml-5 [&_li]:list-disc [&_p]:my-2">
                <ObsidianMarkdown
                  body={note.body}
                  resolveImage={resolveImage}
                  resolveWikilink={resolveWikilink}
                  onWikilinkClick={scrollToNote}
                />
              </div>
            </div>
          ))}

          <h3 className="mb-2 mt-6 text-accent-bright font-semibold">Images</h3>
          <div className="mb-3 flex flex-wrap gap-2">
            {attachments.length === 0 ? (
              <p className="text-sm text-text-muted">No images yet.</p>
            ) : (
              attachments.map((a) => (
                <a key={a.filename} href={a.url} target="_blank" rel="noopener">
                  <img
                    src={a.url}
                    alt={a.filename}
                    loading="lazy"
                    className="h-30 w-30 rounded-lg border border-[#2a2a2a] object-cover"
                  />
                </a>
              ))
            )}
          </div>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) uploadMutation.mutate(file);
              e.target.value = "";
            }}
            className="mb-6 text-sm text-text-muted"
          />

          <h3 className="mb-2 text-accent-bright font-semibold">
            Chat about this project
          </h3>
          <Toggle
            checked={agentRun}
            onChange={setAgentRun}
            label="Run as agent"
            sublabel='Treats your next message as a goal to complete autonomously (e.g. "research X and write it up") — the assistant will use its tools and save real notes into this project instead of just replying.'
          />

          {isPolling && activityQuery.data && (
            <div className="my-3 flex max-h-55 flex-col gap-1 overflow-y-auto rounded-lg border border-[#2a2a2a] bg-[#1a1a1a] px-3 py-2.5">
              {activityQuery.data.steps.map((step, i) => (
                <div
                  key={i}
                  className="whitespace-pre-wrap wrap-break-word font-mono text-xs text-[#aaaaaa]">
                  {step.type === "calling"
                    ? `→ ${step.tool}(${JSON.stringify(step.args)})`
                    : `✓ ${step.tool}: ${step.content}`}
                </div>
              ))}
            </div>
          )}

          <ChatWidget
            threadId={threadId}
            mode="project_chat"
            agentRun={agentRun}
            greeting={`Ask anything about the "${projectName}" project.`}
            alwaysGreetIfEmpty
            onSendStart={() => {
              if (!agentRun) return;
              queryClient.removeQueries({
                queryKey: ["agent-activity", threadId],
              });
              setIsPolling(true);
              setPollReady(false);
              clearTimeout(pollTimeoutRef.current);
              pollTimeoutRef.current = setTimeout(
                () => setPollReady(true),
                1200,
              );
            }}
            onReply={() =>
              queryClient.invalidateQueries({
                queryKey: ["project", projectName],
              })
            }
          />
        </>
      )}
    </Card>
  );
}
