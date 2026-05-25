# typed: false
# frozen_string_literal: true

class Teridex < formula
  include Language::Python::Virtualenv

  desc "Modern, terminal-native database IDE — keyboard-first, async, pluggable"
  homepage "https://github.com/salvatorecorvaglia/teridex"
  url "https://github.com/salvatorecorvaglia/teridex/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "PLACEHOLDER"
  license "MIT"

  head "https://github.com/salvatorecorvaglia/teridex.git", branch: "main"

  depends_on "python@3.13"

  def install
    venv = virtualenv_create(libexec, "python3.13")
    pip = libexec/"bin/pip"

    # ── workspace packages (dependency order) ───────────────────────────
    venv.pip_install buildpath/"packages/teridex-core"
    venv.pip_install buildpath/"packages/teridex-plugins"
    # Extras syntax requires the shell form so pip sees `[all]`.
    system pip, "install", "#{buildpath}/packages/teridex-adapters[all]"
    venv.pip_install buildpath/"packages/teridex-engine"
    venv.pip_install buildpath/"apps/teridex-tui"

    # ── CLI entry-point (creates the `teridex` console script) ──────────
    venv.pip_install_and_link buildpath/"apps/teridex-cli"
  end

  test do
    assert_match "teridex", shell_output("#{bin}/teridex version 2>&1")
  end
end
