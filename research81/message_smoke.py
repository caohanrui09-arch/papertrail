from gsearch.state_constraints import ActionState

state = ActionState({'intent': 'search'})
for name, arguments in [
    ('search_papers', {'query': 'x', 'k': None}),
    ('read_paper', {'doc_id': 'never-returned'}),
]:
    try:
        state.validate(name, arguments)
    except ValueError as error:
        print(f'{name}: {error}')
