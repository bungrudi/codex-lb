## ADDED Requirements

### Requirement: Dashboard periodic warm-up controls

The dashboard Settings page SHALL expose controls for periodic account warm-up. The controls SHALL allow an operator to enable or disable periodic warm-up, set the interval in whole hours, set the model, set the prompt, and choose the target scope. The dashboard SHALL validate periodic warm-up settings before enabling save using the same bounds as the backend API.

#### Scenario: Configure periodic warm-up from Settings
- **WHEN** an operator opens Settings
- **THEN** the dashboard shows periodic warm-up controls for enabled state, interval hours, model, prompt, and target scope

#### Scenario: Save periodic warm-up settings
- **WHEN** an operator saves valid periodic warm-up settings
- **THEN** the app calls `PUT /api/settings` with the periodic warm-up fields
- **AND** the saved settings response is reflected in the UI

#### Scenario: Reject invalid periodic warm-up settings in the UI
- **WHEN** an operator enters a blank model, blank prompt, or interval below one hour
- **THEN** the dashboard does not enable saving those invalid values

### Requirement: Dashboard surfaces periodic warm-up account status

Account-facing dashboard views SHALL surface recent periodic warm-up status when the backend provides it. When periodic warm-up target scope is account opt-in, account views SHALL expose an accessible per-account opt-in control.

#### Scenario: Account views show last periodic warm-up attempt
- **WHEN** account summaries include periodic warm-up status
- **THEN** the dashboard shows the latest attempt status, model, and completion or attempt time for each account

#### Scenario: Account opt-in control is accessible
- **GIVEN** periodic warm-up target scope is `account_opt_in`
- **WHEN** an operator views an account row or account details
- **THEN** the per-account periodic warm-up opt-in control has an accessible name that identifies the account context
