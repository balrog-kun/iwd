/*
 *
 *  Wireless daemon for Linux
 *
 *  Copyright (C) 2013-2014  Intel Corporation. All rights reserved.
 *
 *  This library is free software; you can redistribute it and/or
 *  modify it under the terms of the GNU Lesser General Public
 *  License as published by the Free Software Foundation; either
 *  version 2.1 of the License, or (at your option) any later version.
 *
 *  This library is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 *  Lesser General Public License for more details.
 *
 *  You should have received a copy of the GNU Lesser General Public
 *  License along with this library; if not, write to the Free Software
 *  Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
 *
 */

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#include <errno.h>
#include <ell/ell.h>

#include "ie.h"

void ie_tlv_iter_init(struct ie_tlv_iter *iter, const unsigned char *tlv,
			unsigned int len)
{
	iter->tlv = tlv;
	iter->max = len;
	iter->pos = 0;
}

void ie_tlv_iter_recurse(struct ie_tlv_iter *iter,
				struct ie_tlv_iter *recurse)
{
	recurse->tlv = iter->data;
	recurse->max = iter->len;
	recurse->pos = 0;
}

unsigned int ie_tlv_iter_get_tag(struct ie_tlv_iter *iter)
{
	return iter->tag;
}

bool ie_tlv_iter_next(struct ie_tlv_iter *iter)
{
	const unsigned char *tlv = iter->tlv + iter->pos;
	const unsigned char *end = iter->tlv + iter->max;
	unsigned int tag;
	unsigned int len;

	if (iter->pos >= iter->max)
		return false;

	tag = *tlv++;
	len = *tlv++;

	if (tlv + len > end)
		return false;

	iter->tag = tag;
	iter->len = len;
	iter->data = tlv;

	iter->pos = tlv + len - iter->tlv;

	return true;
}

#define TLV_HEADER_LEN 2

static bool ie_tlv_builder_init_recurse(struct ie_tlv_builder *builder,
					unsigned char *tlv, unsigned int size)
{
	if (!builder)
		return false;

	if (!tlv) {
		memset(builder->buf, 0, MAX_BUILDER_SIZE);
		builder->tlv = builder->buf;
		builder->max = MAX_BUILDER_SIZE;
	} else {
		builder->tlv = tlv;
		builder->max = size;
	}

	builder->pos = 0;
	builder->parent = NULL;
	builder->tag = 0xffff;
	builder->len = 0;

	return true;
}

bool ie_tlv_builder_init(struct ie_tlv_builder *builder)
{
	return ie_tlv_builder_init_recurse(builder, NULL, 0);
}

static void ie_tlv_builder_write_header(struct ie_tlv_builder *builder)
{
	unsigned char *tlv = builder->tlv + builder->pos;

	tlv[0] = builder->tag;
	tlv[1] = builder->len;
}

bool ie_tlv_builder_set_length(struct ie_tlv_builder *builder,
					unsigned int new_len)
{
	unsigned int new_pos = builder->pos + TLV_HEADER_LEN + new_len;

	if (new_pos > builder->max)
		return false;

	if (builder->parent)
		ie_tlv_builder_set_length(builder->parent, new_pos);

	builder->len = new_len;

	return true;
}

bool ie_tlv_builder_next(struct ie_tlv_builder *builder, unsigned int new_tag)
{
	if (new_tag > 0xff)
		return false;

	if (builder->tag != 0xffff) {
		ie_tlv_builder_write_header(builder);
		builder->pos += TLV_HEADER_LEN + builder->len;
	}

	if (!ie_tlv_builder_set_length(builder, 0))
		return false;

	builder->tag = new_tag;

	return true;
}

unsigned char *ie_tlv_builder_get_data(struct ie_tlv_builder *builder)
{
	return builder->tlv + TLV_HEADER_LEN + builder->pos;
}

bool ie_tlv_builder_recurse(struct ie_tlv_builder *builder,
					struct ie_tlv_builder *recurse)
{
	unsigned char *end = builder->buf + builder->max;
	unsigned char *data = ie_tlv_builder_get_data(builder);

	if (!ie_tlv_builder_init_recurse(recurse, data, end - data))
		return false;

	recurse->parent = builder;

	return true;
}

void ie_tlv_builder_finalize(struct ie_tlv_builder *builder,
			unsigned int *out_len)
{
	unsigned int len;

	ie_tlv_builder_write_header(builder);

	len = builder->pos + TLV_HEADER_LEN + builder->len;

	if (out_len)
		*out_len = len;
}
