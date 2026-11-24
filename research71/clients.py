"""Bind custom searches to the user's confirmed query; never repair a proposal."""
from gsearch.unified_agent import ToolClient
from gsearch.constrained_agent import GuardedClient
from research70.observability import ObserveCalls


def enforces_query(task: dict) -> bool:
    """A custom task binds the query unless the plan handed query choice to the agent."""
    return task.get('task_kind') == 'custom' and task.get('query_mode') != 'model'


class ConfirmedQuery:
    def __init__(self,task,*args,**kwargs):
        self.confirmed_query=task['query'] if enforces_query(task) else None
        super().__init__(task,*args,**kwargs)

    def call(self,name,**arguments):
        if name=='search_papers' and self.confirmed_query is not None and arguments.get('query')!=self.confirmed_query:
            raise ValueError('Search query must exactly match the user-confirmed query; no silent rewriting')
        return super().call(name,**arguments)


class ObservedCustomClient(ObserveCalls,ConfirmedQuery,ToolClient):
    pass


class ObservedCustomGuardedClient(ObserveCalls,ConfirmedQuery,GuardedClient):
    pass
