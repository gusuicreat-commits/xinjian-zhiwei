import { mount } from '@vue/test-utils'

import StatusBadge from './StatusBadge.vue'

describe('StatusBadge', () => {
  it('renders the healthy service state', () => {
    const wrapper = mount(StatusBadge, { props: { online: true } })

    expect(wrapper.text()).toContain('服务正常')
    expect(wrapper.classes()).toContain('status-badge')
    expect(wrapper.find('.is-online').exists()).toBe(true)
  })

  it('renders the disconnected state', () => {
    const wrapper = mount(StatusBadge, { props: { online: false } })

    expect(wrapper.text()).toContain('连接异常')
    expect(wrapper.find('.is-offline').exists()).toBe(true)
  })
})
