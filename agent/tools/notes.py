from langchain_core.tools import tool
from agent.memory import MemoryStore

    
def make_note_tools(memory: MemoryStore):
    """
    Returns the save_note and search_notes tools with the MemoryStore
    injected via closure.  Called once at startup inside get_tools().
    """

    @tool
    def save_note(content: str, title: str = None) -> str:
        """Save a note. Use this when the user wants to jot something down,
        remember something, or make a note of something.

        Args:
            content: The body of the note.
            title: Optional title for the note.
        """
        note_id = memory.save_note(content, title=title)
        heading = title or "Note"
        return f"Note saved: '{heading}' (id: {note_id})."



    @tool
    def search_notes(query: str) -> str:
        """Search previously saved notes for information.
 
        Args:
            query: What to search for in past notes.
        """
        results = memory.search_notes(query, n_results=3)
        if not results:
            return "No matching notes found."
        lines = []
        for r in results:
            lines.append(f"[{r['title']}] {r['content']}")
        return "\n---\n".join(lines)

    return save_note, search_notes
