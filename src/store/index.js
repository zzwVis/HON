import { createStore } from 'vuex';

const store = createStore({
    state() {
        return {
            globalHighlight: [],
        };
    },
    mutations: {
        setGlobalHighlight(state,option) {
            state.globalHighlight.push(option);
        },
    },
    actions: {
        saveGlobalHighlight({ commit }, option) {
            commit('setGlobalHighlight', option);
        },
    }
});

export default store;