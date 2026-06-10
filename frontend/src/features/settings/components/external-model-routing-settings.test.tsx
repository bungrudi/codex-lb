import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ExternalModelRoutingSettings } from "@/features/settings/components/external-model-routing-settings";
import { createExternalModelRoutingAdmin } from "@/test/mocks/factories";

describe("ExternalModelRoutingSettings", () => {
  it("creates providers and routes without exposing provider secrets", async () => {
    const user = userEvent.setup();
    const onCreateProvider = vi.fn().mockResolvedValue(undefined);
    const onCreateRoute = vi.fn().mockResolvedValue(undefined);

    render(
      <ExternalModelRoutingSettings
        admin={createExternalModelRoutingAdmin({ providers: [], routes: [] })}
        busy={false}
        onCreateProvider={onCreateProvider}
        onUpdateProvider={vi.fn().mockResolvedValue(undefined)}
        onDeleteProvider={vi.fn().mockResolvedValue(undefined)}
        onCreateRoute={onCreateRoute}
        onUpdateRoute={vi.fn().mockResolvedValue(undefined)}
        onDeleteRoute={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await user.clear(screen.getByLabelText("External provider id"));
    await user.type(screen.getByLabelText("External provider id"), "openrouter");
    await user.type(screen.getByLabelText("External provider API key"), "test-secret");
    await user.click(screen.getByRole("button", { name: "Create provider" }));

    expect(onCreateProvider).toHaveBeenCalledWith({
      id: "openrouter",
      kind: "openai_compatible",
      baseUrl: "https://openrouter.ai/api/v1",
      apiKey: "test-secret",
      apiKeyEnv: null,
      defaultHeaders: {},
      timeoutSeconds: 600,
      streamIdleTimeoutSeconds: 600,
      isActive: true,
      allowInsecureBaseUrl: false,
    });
    expect(screen.queryByText("test-secret")).not.toBeInTheDocument();
  });

  it("updates provider keys and route targets", async () => {
    const user = userEvent.setup();
    const onUpdateProvider = vi.fn().mockResolvedValue(undefined);
    const onUpdateRoute = vi.fn().mockResolvedValue(undefined);

    render(
      <ExternalModelRoutingSettings
        admin={createExternalModelRoutingAdmin()}
        busy={false}
        onCreateProvider={vi.fn().mockResolvedValue(undefined)}
        onUpdateProvider={onUpdateProvider}
        onDeleteProvider={vi.fn().mockResolvedValue(undefined)}
        onCreateRoute={vi.fn().mockResolvedValue(undefined)}
        onUpdateRoute={onUpdateRoute}
        onDeleteRoute={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await user.type(screen.getByLabelText("API key for external provider openrouter"), "test-new");
    await user.click(screen.getByRole("button", { name: "Update key" }));
    expect(onUpdateProvider).toHaveBeenCalledWith("openrouter", { apiKey: "test-new" });

    await user.clear(screen.getByLabelText("Target model for external route Minimax Codex"));
    await user.type(screen.getByLabelText("Target model for external route Minimax Codex"), "new/model");
    await user.click(screen.getByRole("button", { name: "Retarget" }));
    expect(onUpdateRoute).toHaveBeenCalledWith("route_minimax_codex", {
      targetModel: "new/model",
      deactivateConflicts: true,
    });
  });
});
