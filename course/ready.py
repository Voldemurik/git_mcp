"""Suggested ready-MCP connection helper; no domain solution is provided.

Only vetted endpoints and directory-restricted local servers. Connecting a
ready MCP is not a substitute for writing your own MCP or agent.
"""
from __future__ import annotations
import os,sys,subprocess
from contextlib import contextmanager
from pathlib import Path
from .protocol import MCPStdio,MCPRemoteHTTP,child_env,ProtocolError

class OwnRepoGitVerse:
    """Read-only wrapper: reject GitVerse requests beyond student's fork."""
    def __init__(self, client, repository):
        if '/' not in repository:raise ProtocolError('GITVERSE_REPOSITORY allowlist missing')
        self.client=client
        self.owner,self.repo=repository.split('/',1)
    def list_tools(self):return self.client.list_tools()
    def call(self,name,args):
        if name not in ('get_repository','get_repository_content','list_branches','actions_list'):
            raise ProtocolError('GitVerse operation not allowlisted')
        if not isinstance(args,dict) or args.get('owner') != self.owner or args.get('repo') != self.repo:
            raise ProtocolError('GitVerse repository outside own fork')
        if name == 'get_repository_content' and (args.get('path','') not in ('README.md','TASK.md','variant.json')):
            raise ProtocolError('GitVerse file read not allowlisted')
        return self.client.call(name,args)


@contextmanager
def connect_ready(root:Path, ready_name:str):
    root=Path(root).resolve()
    name=ready_name.strip().lower()
    if name=='context7':
        with MCPRemoteHTTP('context7', os.getenv('CONTEXT7_API_KEY','')) as c:yield c
    elif name=='gitverse':
        with MCPRemoteHTTP('gitverse',os.getenv('MCP_GITVERSE_TOKEN','')) as c:
            yield OwnRepoGitVerse(c,os.getenv('GITVERSE_REPOSITORY',''))
    elif name=='filesystem':
        # The ready server can read the assignment only, never outputs/ or secrets.
        cmd=['npx','-y','@modelcontextprotocol/server-filesystem@2.3.0',
             '--read-only',str(root/'case')]
        with MCPStdio(cmd,root,child_env(root),timeout=60) as c:yield c
    elif name=='git':
        # Restore the supplied Git bundle into a disposable directory.
        bundle=root/'case/fixture.bundle'
        work=root/'_workspaces/git_fixture'
        if not bundle.is_file():raise ProtocolError('case/fixture.bundle is missing')
        if work.exists():
            import shutil;shutil.rmtree(work)
        work.parent.mkdir(parents=True,exist_ok=True)
        proc=subprocess.run(['git','clone','-q',str(bundle),str(work)],capture_output=True,text=True,timeout=30)
        if proc.returncode:raise ProtocolError('Could not restore Git fixture')
        cmd=[sys.executable,'-m','mcp_server_git','--repository',str(work)]
        with MCPStdio(cmd,root,child_env(root),timeout=60) as c:yield c
    else:raise ValueError('Unapproved ready MCP provider: '+name)
