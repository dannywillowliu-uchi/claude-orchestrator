"""Task feasibility analyzer - determines if Claude can complete a task."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TaskComplexity(str, Enum):
    SIMPLE = "simple"      # Single tool call, < 5 steps
    MODERATE = "moderate"  # Multiple tools, 5-15 steps
    COMPLEX = "complex"    # Needs planning, subagents, > 15 steps


@dataclass
class FeasibilityResult:
    can_do: bool
    score: float  # 0.0 to 1.0
    reason: str
    complexity: TaskComplexity
    required_tools: list[str]
    blockers: list[str]
    suggested_plan: Optional[str] = None


class TaskAnalyzer:
    """Analyzes tasks to determine if Claude Code can complete them."""

    # Keywords indicating tasks Claude CAN do
    CAN_DO_KEYWORDS = [
        # Coding tasks
        "write code", "create file", "edit file", "modify file", "update file",
        "implement", "add function", "add feature", "refactor", "optimize",
        "fix bug", "debug", "write test", "add test", "write tests",
        # Git operations
        "git commit", "git push", "commit", "push", "create branch", "merge",
        "create pr", "pull request",
        # File operations
        "create folder", "create directory", "move file", "rename file",
        "delete file", "copy file", "organize files",
        # Analysis
        "analyze", "review", "explain", "summarize", "document",
        "search code", "find", "look up", "check",
        # Shell commands
        "run command", "run script", "execute", "install", "npm", "pip",
        "build", "compile", "deploy",
        # Research
        "research", "search web", "find information", "look up documentation",
    ]

    # Keywords indicating tasks Claude CANNOT do
    CANNOT_DO_KEYWORDS = [
        # Physical actions
        "physical", "hardware", "device", "printer", "scan",
        "call someone", "phone call", "meeting", "schedule meeting",
        "pick up", "drop off", "deliver",
        # Real-time/continuous
        "monitor continuously", "watch", "wait for", "real-time",
        "keep checking", "notify when",
        # External services without credentials
        "send email", "post to twitter", "tweet", "post to instagram",
        "send sms", "text message",
        # Decisions requiring human judgment
        "decide", "choose for me", "should i",
        # Payments/financial
        "pay", "transfer money", "buy", "purchase", "order",
    ]

    # Tools Claude Code has access to
    AVAILABLE_TOOLS = [
        "read_file", "write_file", "edit_file", "glob", "grep",
        "bash", "git", "web_search", "web_fetch",
        "task_agent", "code_reviewer", "plan_agent",
    ]

    def analyze(self, title: str, notes: Optional[str] = None) -> FeasibilityResult:
        """
        Analyze a task to determine if Claude can complete it.

        Returns FeasibilityResult with feasibility score, complexity, and plan.
        """
        full_text = f"{title} {notes or ''}".lower()

        # Check for definite blockers
        blockers = self._find_blockers(full_text)
        if blockers:
            return FeasibilityResult(
                can_do=False,
                score=0.1,
                reason=f"Task requires: {', '.join(blockers)}",
                complexity=TaskComplexity.COMPLEX,
                required_tools=[],
                blockers=blockers,
            )

        # Check for capabilities
        capabilities = self._find_capabilities(full_text)
        required_tools = self._identify_tools(full_text)
        complexity = self._assess_complexity(full_text, capabilities)

        # Calculate score based on matches
        if capabilities:
            base_score = 0.7 + (len(capabilities) * 0.05)
            score = min(base_score, 0.95)
            can_do = True
            reason = f"Can handle: {', '.join(capabilities[:3])}"
        else:
            # Ambiguous - might be possible
            score = 0.5
            can_do = True
            reason = "Task seems doable but may need clarification"

        # Generate suggested plan
        suggested_plan = self._generate_plan(title, notes, capabilities, complexity)

        return FeasibilityResult(
            can_do=can_do,
            score=score,
            reason=reason,
            complexity=complexity,
            required_tools=required_tools,
            blockers=[],
            suggested_plan=suggested_plan,
        )

    def _find_blockers(self, text: str) -> list[str]:
        """Find keywords that indicate Claude cannot do this task."""
        blockers = []
        for keyword in self.CANNOT_DO_KEYWORDS:
            if keyword in text:
                blockers.append(keyword)
        return blockers

    def _find_capabilities(self, text: str) -> list[str]:
        """Find keywords that indicate Claude can do this task."""
        capabilities = []
        for keyword in self.CAN_DO_KEYWORDS:
            if keyword in text:
                capabilities.append(keyword)
        return capabilities

    def _identify_tools(self, text: str) -> list[str]:
        """Identify which tools would be needed for this task."""
        tools = []

        # File operations
        if any(k in text for k in ["read", "open", "view", "check file"]):
            tools.append("read_file")
        if any(k in text for k in ["write", "create file", "save"]):
            tools.append("write_file")
        if any(k in text for k in ["edit", "modify", "update", "change"]):
            tools.append("edit_file")

        # Search operations
        if any(k in text for k in ["find", "search", "look for", "grep"]):
            tools.append("grep")
        if any(k in text for k in ["list files", "find files", "glob"]):
            tools.append("glob")

        # Git operations
        if any(k in text for k in ["git", "commit", "push", "branch", "merge"]):
            tools.append("git")

        # Shell operations
        if any(k in text for k in ["run", "execute", "install", "build", "npm", "pip"]):
            tools.append("bash")

        # Web operations
        if any(k in text for k in ["search web", "google", "look up online"]):
            tools.append("web_search")
        if any(k in text for k in ["fetch url", "get page", "download"]):
            tools.append("web_fetch")

        # Complex operations needing agents
        if any(k in text for k in ["review", "analyze code"]):
            tools.append("code_reviewer")
        if any(k in text for k in ["plan", "design", "architect"]):
            tools.append("plan_agent")

        return list(set(tools))

    def _assess_complexity(self, text: str, capabilities: list[str]) -> TaskComplexity:
        """Assess the complexity of a task."""
        # Simple indicators
        simple_keywords = [
            "simple", "quick", "just", "only", "single",
            "one file", "small change", "typo", "rename",
        ]

        # Complex indicators
        complex_keywords = [
            "implement", "feature", "refactor", "redesign",
            "multiple files", "across", "entire", "all",
            "create system", "build", "develop",
        ]

        simple_count = sum(1 for k in simple_keywords if k in text)
        complex_count = sum(1 for k in complex_keywords if k in text)

        if simple_count > complex_count and complex_count == 0:
            return TaskComplexity.SIMPLE
        elif complex_count >= 2 or len(capabilities) > 5:
            return TaskComplexity.COMPLEX
        else:
            return TaskComplexity.MODERATE

    def _generate_plan(
        self,
        title: str,
        notes: Optional[str],
        capabilities: list[str],
        complexity: TaskComplexity,
    ) -> str:
        """Generate a suggested execution plan."""
        steps = []

        # Determine task type and generate appropriate steps
        title_lower = title.lower()

        if any(k in title_lower for k in ["create", "write", "implement", "add"]):
            steps = [
                "1. Understand the requirements from task description",
                "2. Search codebase for similar patterns/examples",
                "3. Identify the target file(s) to create/modify",
                "4. Implement the changes",
                "5. Run tests to verify",
                "6. Report completion",
            ]
        elif any(k in title_lower for k in ["fix", "debug", "bug"]):
            steps = [
                "1. Locate the buggy code/behavior",
                "2. Understand the root cause",
                "3. Implement the fix",
                "4. Test the fix",
                "5. Report completion",
            ]
        elif any(k in title_lower for k in ["refactor", "optimize", "improve"]):
            steps = [
                "1. Analyze current implementation",
                "2. Identify improvement opportunities",
                "3. Plan the refactoring approach",
                "4. Make incremental changes",
                "5. Ensure tests still pass",
                "6. Report completion",
            ]
        elif any(k in title_lower for k in ["review", "analyze", "check"]):
            steps = [
                "1. Read the relevant files",
                "2. Analyze the code/content",
                "3. Document findings",
                "4. Report results",
            ]
        else:
            # Generic plan
            steps = [
                "1. Understand the task requirements",
                "2. Explore relevant code/files",
                "3. Execute the task",
                "4. Verify completion",
                "5. Report results",
            ]

        if complexity == TaskComplexity.COMPLEX:
            steps.insert(0, "0. Break down into subtasks using planning agent")

        return "\n".join(steps)
