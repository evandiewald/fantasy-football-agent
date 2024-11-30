import pandas as pd
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables.config import RunnableConfig

import streamlit as st
from sleeper import SleeperClient
from league import League
from typing import Dict, Callable

import config as cf

from langgraph.pregel.remote import RemoteGraph

url_for_langgraph_api = 'http://localhost:8123'

remote_graph = RemoteGraph('chatbot', url=url_for_langgraph_api)
sleeper = SleeperClient()

def get_tool_name_to_fn(config: RunnableConfig) -> Dict[str, Callable]:
    league = League(league_id=config['configurable']['league_id'])
    tool_name_to_fn: Dict[str, Callable] = {
        'get_player_stats': league.get_player_stats_df,
        'get_league_status': league.get_league_standings_df,
        'get_roster_for_team_owner': league.get_roster_for_team_owner_df,
        'get_player_news': league.get_player_news,
        'get_player_current_owner': league.get_player_current_owner,
        'get_best_available_at_position': league.get_best_available_at_position_df,
    }
    return tool_name_to_fn

def generate_response(message: str, config: RunnableConfig):
    chunks = remote_graph.stream(
        {'messages': [HumanMessage(message)]},
        config=config,
        stream_mode='messages'
    )
    for chunk in chunks:
        # print(chunk[0])
        if chunk[0].get('type') == 'tool':
            # add to sources on the side
            continue
        else:
            yield chunk[0]['content']

def process_tool_calls(config: RunnableConfig):
    tool_name_to_fn = get_tool_name_to_fn(config)

    messages = remote_graph.get_state(config).values['messages']
    for m in messages:
        if tool_calls := m.get('tool_calls', []):
            for tc in tool_calls:
                if tc['id'] not in st.session_state['research']:
                    tc_header = tc['name']
                    if tc['args']:
                        tc_header += f" ({', '.join(tc['args'].values())})"
                    st.session_state['research'][tc['id']] = {
                        'name': tc_header,
                        'content': tool_name_to_fn[tc['name']](**tc['args'])
                    }

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

if 'thread_id' not in st.session_state:
    st.session_state.thread_id = remote_graph.sync_client.threads.create()['thread_id']

if 'research' not in st.session_state:
    st.session_state.research = {}

st.title('Fantasy Football Agent')
username = st.text_input('Sleeper Username')

if username:
    if st.button('Clear Chat'):
        for k in st.session_state:
            st.session_state.pop(k)

    user_id = sleeper.get_user(username)['user_id']
    available_leagues = sleeper.get_leagues_for_user(user_id)
    league_name_to_id = {league['name']: league['league_id'] for league in available_leagues}
    league_name = st.selectbox('League Name', options=league_name_to_id.keys())
    league_id = league_name_to_id[league_name]
    st.session_state['league_id'] = league_id

    if league_id:

        config = {
            'configurable': {
                'username': username,
                'league_id': league_id,
                'thread_id': st.session_state['thread_id']
            }
        }

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("What is up?"):
            # Display user message in chat message container
            with st.chat_message("user"):
                st.markdown(prompt)
            # Add user message to chat history
            st.session_state.messages.append({"role": "user", "content": prompt})

            # Display assistant response in chat message container
            with st.chat_message("assistant"):
                response = st.write_stream(generate_response(prompt, config))
            # Add assistant response to chat history
            st.session_state.messages.append({"role": "assistant", "content": response})
            process_tool_calls(config)

            with st.sidebar:
                st.subheader('Compiled Research')
                for r in st.session_state.research.values():
                    with st.expander(r['name']):
                        if isinstance(r['content'], pd.DataFrame):
                            st.dataframe(r['content'])
                        else:
                            st.markdown(r['content'])