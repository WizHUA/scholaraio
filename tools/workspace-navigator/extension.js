// Workspace Navigator — VS Code Extension
// Quickly focus and expand a workspace/ subdirectory in the Explorer.
//
// Usage: Ctrl+Alt+W (Win/Linux) / Cmd+Alt+W (Mac)
//   or:  Command Palette → "Workspace: 定位到项目目录"

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
    const disposable = vscode.commands.registerCommand('workspace-navigator.go', async () => {
        // Locate the workspace root
        const folders = vscode.workspace.workspaceFolders;
        if (!folders || folders.length === 0) {
            vscode.window.showErrorMessage('未打开工作区');
            return;
        }

        const rootPath = folders[0].uri.fsPath;
        const wsDirPath = path.join(rootPath, 'workspace');

        if (!fs.existsSync(wsDirPath)) {
            vscode.window.showErrorMessage(`未找到 workspace/ 目录：${wsDirPath}`);
            return;
        }

        // Read immediate subdirectories of workspace/
        let entries;
        try {
            entries = fs.readdirSync(wsDirPath, { withFileTypes: true })
                .filter(e => e.isDirectory())
                .sort((a, b) => a.name.localeCompare(b.name))
                .map(e => ({
                    label: e.name,
                    description: `workspace/${e.name}`,
                }));
        } catch (err) {
            vscode.window.showErrorMessage(`读取目录失败：${err.message}`);
            return;
        }

        if (entries.length === 0) {
            vscode.window.showInformationMessage('workspace/ 下没有子目录');
            return;
        }

        // Show QuickPick — VS Code handles fuzzy filtering automatically as the user types
        const picked = await vscode.window.showQuickPick(entries, {
            placeHolder: '输入目录名（如 01-）以快速定位',
            matchOnDescription: false,
        });

        if (!picked) return;

        const targetPath = path.join(wsDirPath, picked.label);
        const targetUri = vscode.Uri.file(targetPath);

        // 1. Collapse all folders in the Explorer
        await vscode.commands.executeCommand('workbench.files.action.collapseExplorerFolders');

        // 2. Small delay to let collapse animation finish
        await delay(120);

        // 3. Reveal target in Explorer — expands the path to it and selects it
        await vscode.commands.executeCommand('revealInExplorer', targetUri);

        // 4. Wait for the tree to update, then expand the selected folder one level
        await delay(150);
        await vscode.commands.executeCommand('list.expand');
    });

    context.subscriptions.push(disposable);
}

function deactivate() {}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

module.exports = { activate, deactivate };
